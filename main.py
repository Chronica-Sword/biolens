from fastapi import FastAPI, Request, Depends, Form, HTTPException, Cookie, responses
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel
import time
import urllib.request
import urllib.parse
import json
import os
import re
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
if GEMINI_KEY and GEMINI_KEY != "BURAYA_YAPISTIRIN":
    genai.configure(api_key=GEMINI_KEY)

import models
from database import SessionLocal, engine

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="BioRead Kanban", version="1.0.0")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Simple Auth settings
SHARED_PASSWORD = "bioresearcher"
AUTH_COOKIE_NAME = "bioread_access_token"

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class StatusUpdate(BaseModel):
    status: str

class ArticleCreate(BaseModel):
    doi: str

class SummarizeRequest(BaseModel):
    text: str

class SimplifyRequest(BaseModel):
    article_id: int
    text: str
    level: str # undergrad, grad, expert

def is_authenticated(request: Request):
    return request.cookies.get(AUTH_COOKIE_NAME) == "true_access"

# --- WEB ROUTES ---

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request, db: Session = Depends(get_db)):
    if not is_authenticated(request):
        return templates.TemplateResponse(request=request, name="login.html")
    
    # Get all articles to pass to frontend
    articles = db.query(models.Article).all()
    # Serialize to dict list
    articles_data = []
    for a in articles:
        articles_data.append({
            "id": a.id, "title": a.title, "authors": a.authors,
            "journal": a.journal, "status": a.status, "doi": a.doi
        })
    return templates.TemplateResponse(request=request, name="index.html", context={"articles": articles_data})

@app.post("/login")
async def login(password: str = Form(...)):
    if password == SHARED_PASSWORD:
        response = RedirectResponse(url="/", status_code=302)
        response.set_cookie(key=AUTH_COOKIE_NAME, value="true_access")
        return response
    # Invalid password, redirect to home which will render login again
    return RedirectResponse(url="/?error=1", status_code=302)

@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie(key=AUTH_COOKIE_NAME)
    return response

# --- API ROUTES ---

@app.post("/api/articles")
async def create_article(article_in: ArticleCreate, db: Session = Depends(get_db)):
    if not article_in.doi or article_in.doi.strip() == "":
        raise HTTPException(status_code=400, detail="Lütfen geçerli bir DOI giriniz.")
        
    identifier = article_in.doi.strip()
    identifier_clean = identifier.replace("https://doi.org/", "").replace("http://dx.doi.org/", "").strip()
    
    # Gerçek Makale Verisi Çekme (PubMed veya CrossRef)
    info = {"title": f"Manuel Kayıt: {identifier}", "authors": "Bilinmeyen", "journal": "Bilinmeyen"}
    
    # Eğer sadece numara ise PubMed ID (PMID) varsay
    if identifier_clean.isdigit():
        url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&id={identifier_clean}&retmode=json"
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5) as response:
                meta = json.loads(response.read().decode()).get("result", {}).get(identifier_clean, {})
                info["title"] = meta.get("title", info["title"])
                authors_list = meta.get("authors", [])
                if authors_list:
                    info["authors"] = ", ".join([a.get("name", "") for a in authors_list])
                info["journal"] = meta.get("source", info["journal"])
        except Exception:
            pass
    # Değilse DOI varsayıp CrossRef API'ye git
    else:
        url = f"https://api.crossref.org/works/{urllib.parse.quote(identifier_clean)}"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'BioLens/1.0 (mailto:test@example.com)'})
            with urllib.request.urlopen(req, timeout=5) as response:
                meta = json.loads(response.read().decode()).get("message", {})
                title_list = meta.get("title", [])
                if title_list: info["title"] = title_list[0]
                
                author_list = meta.get("author", [])
                if author_list:
                    parsed_authors = []
                    for a in author_list:
                        fam = a.get('family', '')
                        giv = a.get('given', '')
                        if giv:
                            parsed_authors.append(f"{fam} {giv[0]}.")
                        else:
                            parsed_authors.append(fam)
                    info["authors"] = ", ".join(parsed_authors).strip()
                
                journal_list = meta.get("container-title", [])
                if journal_list: info["journal"] = journal_list[0]
        except Exception:
            pass

    new_article = models.Article(
        title=info["title"],
        authors=info["authors"],
        journal=info["journal"],
        doi=identifier_clean,
        status="toread",
        abstract=""
    )
    db.add(new_article)
    db.commit()
    db.refresh(new_article)
    return new_article

@app.put("/api/articles/{article_id}/status")
async def update_status(article_id: int, status_update: StatusUpdate, db: Session = Depends(get_db)):
    article = db.query(models.Article).filter(models.Article.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    article.status = status_update.status
    db.commit()
    return {"status": "ok"}

@app.get("/api/articles/{article_id}")
async def get_article(article_id: int, db: Session = Depends(get_db)):
    article = db.query(models.Article).filter(models.Article.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return article

@app.put("/api/articles/{article_id}/notes")
async def update_notes(article_id: int, request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    notes = data.get("notes", "")
    article = db.query(models.Article).filter(models.Article.id == article_id).first()
    if article:
        article.personal_notes = notes
        db.commit()
        return {"status": "ok"}
    raise HTTPException(status_code=404)

@app.delete("/api/articles/{article_id}")
async def delete_article(article_id: int, db: Session = Depends(get_db)):
    article = db.query(models.Article).filter(models.Article.id == article_id).first()
    if article:
        db.delete(article)
        db.commit()
        return {"status": "ok"}
    raise HTTPException(status_code=404, detail="Makale bulunamadı")

# --- REAL AI ROUTES ---

@app.post("/api/summarize/{article_id}")
async def summarize_article(article_id: int, db: Session = Depends(get_db)):
    article = db.query(models.Article).filter(models.Article.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Makale bulunamadı")
        
    if not GEMINI_KEY or GEMINI_KEY == "BURAYA_YAPISTIRIN":
        raise HTTPException(status_code=500, detail="Gemini API Anahtarı .env dosyasına girilmemiş! Lütfen dosyayı kontrol edin.")
        
    prompt = f"""
    Sen deneyimli bir Biyoteknoloji doçentisin. Görevin aşağıda verilen makale künyesini inceleyerek,
    kendindeki geniş akademik literatür bilgisi ile bu makalenin içeriğini tahmin edip/gerçek içeriğini çıkartıp
    kullanıcıya yapılandırılmış bir akademik analiz vermektir. Mümkün olduğunca detaylı analiz et. İstenen dil Türkçe.
    
    Makale Başlığı: {article.title}
    Yazarlar: {article.authors}
    Dergi: {article.journal}
    
    Lütfen şu ana başlıkları çıkar. Çıktı SADECE JSON formatında olmalı. Markdown kullanma (```json gibi şeyler yazma), doğrudan sadece saf JSON ver:
    {{
      "abstract": "Orijinal makale veya konu özeti (en az 3 cümle).",
      "keywords": "Anahtar kelimeler (virgülle ayrılmış)",
      "methodology": "Makalede kullanılan temel yöntemler (en az 3 cümle).",
      "key_findings": "En önemli bulgular (en az 4 cümle).",
      "limitations": "Çalışmanın temel kısıtlamaları (en az 2 cümle)."
    }}
    """
    
    try:
        model = genai.GenerativeModel('gemini-3-flash-preview')
        response = model.generate_content(prompt)
        raw_text = response.text.strip()
        
        # Daha güvenli JSON ayıklama (regex ile)
        match = re.search(r'\{.*\}', raw_text, re.DOTALL)
        if match:
            raw_text = match.group(0)
            
        data = json.loads(raw_text.strip())
        
        article.methodology = data.get("methodology") or "Bilgi bulunamadı."
        article.key_findings = data.get("key_findings") or "Bilgi bulunamadı."
        article.limitations = data.get("limitations") or "Bilgi bulunamadı."
        article.abstract = data.get("abstract") or "Bilgi bulunamadı."
        article.keywords = data.get("keywords") or ""
        
        db.commit()
        db.refresh(article)
        
        return {
            "methodology": article.methodology, 
            "key_findings": article.key_findings, 
            "limitations": article.limitations,
            "abstract": article.abstract,
            "keywords": article.keywords
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Yapay Zeka Hatası: {str(e)}")

@app.post("/api/simplify")
async def simplify_text(req: SimplifyRequest, db: Session = Depends(get_db)):
    if not GEMINI_KEY or GEMINI_KEY == "BURAYA_YAPISTIRIN":
        raise HTTPException(status_code=500, detail="Gemini API Anahtarı eksik!")
        
    article = db.query(models.Article).filter(models.Article.id == req.article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Makale bulunamadı")
        
    if req.level == "undergrad":
        if article.simplified_text:
            return {"text": article.simplified_text}
            
        prompt = f"""
        Sen bir biyoteknoloji profesörüsün. Bugün amfide lisans 1. sınıf öğrencilerine bilimsel bir ders veriyorsun.
        Elinde zor ve akademik olan şu veri (makale bileşenleri) var: 
        '{req.text}'
        
        Bu karmaşık metni amfideki lisans öğrencilerine adeta bir hikaye anlatıyormuş gibi heyecanla, terimlerin kökenini açıklayarak ve pedagojik olarak 
        uzunca (en az 800 kelime) "Ders Notu (Lecture)" şeklinde anlatarak basitleştir. Gerekirse vurgu için HTML <b> etiketleri ve paragraflar için <br><br> kullan. Öğrencileri tebrik et ve derse hoşgeldiniz de. Bu bir sohbet botu mesajı değil, doğrudan akademik bir transkript gibi olsun.
        """
        try:
            model = genai.GenerativeModel('gemini-3-flash-preview')
            response = model.generate_content(prompt)
            
            article.simplified_text = response.text
            db.commit()
            
            return {"text": response.text}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Yapay Zeka Hatası: {str(e)}")
    else:
        return {"text": req.text}

@app.get("/api/tooltip")
async def mock_tooltip(word: str):
    dictionary = {
        "iptg": "İzopropil β-d-1-tiyogalaktopiranosid. Lak operonunu indükleyerek rekombinant protein ifadesini tetikleyen kimyasal.",
        "mabs": "Monoclonal Antibodies (Monoklonal Antikorlar): Tek bir B hücresi klonundan üretilen özdeş yapılı bağışıklık sistemi proteinleridir. Hedefli tedavilerde sıkça kullanılır.",
        "ipscs": "Induced Pluripotent Stem Cells: Yetişkin hücrelerden genetik yeniden programlama (reprogramming) yoluyla üretilen embriyonik kök hücre benzeri hücreler (Yamanaka faktörleri ile).",
        "pcr": "Polimeraz Zincir Reaksiyonu: DNA'nın belirli bir bölgesini in vitro (tüpte) milyonlarca kat çoğaltmaya yarayan teknik.",
        "crispr": "Bakterilerin virüslere karşı kullandığı savunma sisteminden ilham alınan devrimsel bir gen düzenleme (gene editing) teknolojisi."
    }
    
    clean_word = word.lower().strip()
    return {"definition": dictionary.get(clean_word, "Bu terim veritabanında bulunmuyor, internetten çekilebilir.")}
