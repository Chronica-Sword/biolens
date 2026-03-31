document.addEventListener('DOMContentLoaded', () => {
    
    // --- KANBAN INITIALIZATION ---
    const columns = ['toread', 'reading', 'used'];
    
    columns.forEach(col => {
        const el = document.getElementById(col);
        new Sortable(el, {
            group: 'shared', // set both lists to same group
            animation: 150,
            ghostClass: 'sortable-ghost',
            onEnd: async function (evt) {
                const itemEl = evt.item;  // dragged HTMLElement
                const newStatus = evt.to.dataset.status; // target list status
                
                if(evt.from === evt.to) return; // Didn't change column
                
                const articleId = itemEl.dataset.id;
                
                // Call API
                try {
                    await fetch(`/api/articles/${articleId}/status`, {
                        method: 'PUT',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({status: newStatus})
                    });
                    updateCounts();
                } catch(e) { console.error('Error updating status', e); }
            },
        });
    });

    function updateCounts() {
        columns.forEach(col => {
            const count = document.getElementById(col).children.length;
            document.getElementById(`count-${col}`).innerText = count;
        });
    }
    updateCounts();

    // --- NEW ARTICLE ADDITION ---
    document.getElementById('new-article-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const doiInput = document.getElementById('doi');
        const val = doiInput.value.trim();
        if(!val) return;
        
        const btn = e.target.querySelector('button[type="submit"]');
        const oldText = btn.innerText;
        btn.innerText = "...";
        btn.disabled = true;

        try {
            const res = await fetch('/api/articles', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({doi: val})
            });
            if(!res.ok) throw new Error("Makale eklenemedi veya sunucu hatası.");
            
            const data = await res.json();
            // Create a fake card locally instead of full refresh for fast UX
            const card = document.createElement('div');
            card.className = "article-card glass-panel";
            card.dataset.id = data.id;
            card.innerHTML = `<div class="card-title">${data.title}</div>
                              <div class="card-meta">${data.journal} • ${data.authors}</div>`;
            document.getElementById('toread').prepend(card);
            doiInput.value = '';
            updateCounts();
            attachClickToCards(); // reattach
        } catch(err) { 
            alert(err.message); 
        } finally {
            btn.innerText = oldText;
            btn.disabled = false;
        }
    });

    // --- MODAL & AI LOGIC ---
    let currentArticleId = null;
    let originalAiText = "";

    const modal = document.getElementById('article-modal');
    
    function attachClickToCards() {
        document.querySelectorAll('.article-card').forEach(card => {
            // Remove old listeners to avoid duplicates
            const newCard = card.cloneNode(true);
            card.parentNode.replaceChild(newCard, card);
            
            newCard.addEventListener('click', () => openModal(newCard.dataset.id));
        });
    }
    attachClickToCards();

    document.getElementById('close-modal').addEventListener('click', () => {
        modal.classList.remove('active');
        document.getElementById('tooltip-box').style.opacity = 0;
    });

    async function openModal(id) {
        currentArticleId = id;
        modal.classList.add('active');
        document.getElementById('ai-content-box').innerHTML = "<em>Yükleniyor...</em>";
        
        try {
            const res = await fetch(`/api/articles/${id}`);
            if(!res.ok) throw new Error("Makale yüklenemedi.");
            const article = await res.json();
            
            document.getElementById('modal-title').innerText = article.title;
            document.getElementById('modal-authors').innerText = `${article.authors} - ${article.journal}`;
            document.getElementById('modal-notes').value = article.personal_notes || "";
            
            // Ask for mock AI summarize if we don't have it
            if(!article.methodology || article.methodology === "Bilgi bulunamadı.") {
                document.getElementById('ai-content-box').innerHTML = "<em>Yükleniyor... Yapay zeka makaleyi ilk kez analiz ediyor... (Yaklaşık 10-15s)</em>";
                const aiRes = await fetch(`/api/summarize/${id}`, {method: 'POST'});
                if(!aiRes.ok) throw new Error("Özetleme başarısız.");
                const aiData = await aiRes.json();
                renderAiContent(aiData);
            } else {
                renderAiContent(article);
            }
            
            // Reset slider
            document.getElementById('difficulty-slider').value = 1;
        } catch (e) { 
            document.getElementById('ai-content-box').innerHTML = `<em>${e.message}</em>`;
        }
    }

    function renderAiContent(data) {
        // Embed some bioterms for tooltip demonstration globally
        let textMeth = (data.methodology || "").replace(/CRISPR/g, '<span class="bioterm">CRISPR</span>').replace(/iPSCs/g, '<span class="bioterm">iPSCs</span>');
        
        let html = `<strong>Özet:</strong> ${(data.abstract||"Yok")}<br><br>` + 
                   `<strong>Anahtar Kelimeler:</strong> ${(data.keywords||"Yok")}<br><br>` + 
                   `<strong>Metodoloji:</strong> ${textMeth}<br><br>` +
                   `<strong>Bulgular:</strong> ${data.key_findings}<br><br>` +
                   `<strong>Kısıtlamalar:</strong> ${data.limitations}`;
        
        originalAiText = html;
        document.getElementById('ai-content-box').innerHTML = html;
        attachTooltips();
    }

    // --- DIFFICULTY SLIDER ---
    document.getElementById('difficulty-slider').addEventListener('change', async (e) => {
        const val = e.target.value; // 0=undergrad, 1=expert
        const box = document.getElementById('ai-content-box');
        
        if (val == 1) {
            box.innerHTML = originalAiText;
            attachTooltips();
            return;
        }
        
        box.innerHTML = "<em>Yapay zeka metni seviyene göre basitleştiriyor...</em>";
        const levelMap = {0: "undergrad"};
        
        try {
            const res = await fetch('/api/simplify', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({article_id: currentArticleId, text: originalAiText, level: levelMap[val]})
            });
            if(!res.ok) throw new Error("İşlem başarısız oldu.");
            const data = await res.json();
            
            // Re-apply tooltip formatting globally
            let textWithTooltips = (data.text || "").replace(/CRISPR/g, '<span class="bioterm">CRISPR</span>').replace(/iPSCs/g, '<span class="bioterm">iPSCs</span>');
            
            box.innerHTML = `<strong>Basitleştirilmiş Makale:</strong><br><br>${textWithTooltips}`;
            attachTooltips();
        } catch(err) { 
            box.innerHTML = "<em>Bir hata oluştu, lütfen tekrar deneyin.</em>";
        }
    });

    // --- TOOLTIPS ---
    const tooltipBox = document.getElementById('tooltip-box');
    
    function attachTooltips() {
        document.querySelectorAll('.bioterm').forEach(el => {
            el.addEventListener('mouseenter', async (e) => {
                const word = e.target.innerText;
                const rect = e.target.getBoundingClientRect();
                
                tooltipBox.innerHTML = "<em>Aranıyor...</em>";
                tooltipBox.style.left = `${rect.left}px`;
                tooltipBox.style.top = `${rect.bottom + 10}px`;
                tooltipBox.style.opacity = 1;

                try {
                    const res = await fetch(`/api/tooltip?word=${encodeURIComponent(word)}`);
                    const data = await res.json();
                    tooltipBox.innerHTML = `<strong>${word}</strong><br>${data.definition}`;
                } catch(e) {}
            });
            
            el.addEventListener('mouseleave', () => {
                tooltipBox.style.opacity = 0;
            });
        });
    }

    // --- NOTES & BIBTEX ---
    document.getElementById('save-notes-btn').addEventListener('click', async () => {
        const notes = document.getElementById('modal-notes').value;
        const btn = document.getElementById('save-notes-btn');
        btn.innerText = "Kaydediliyor...";
        try {
            await fetch(`/api/articles/${currentArticleId}/notes`, {
                method: 'PUT',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({notes: notes})
            });
            btn.innerText = "Kaydedildi!";
            setTimeout(() => { btn.innerText = "Notları Kaydet"; }, 2000);
        } catch (e) { btn.innerText = "Hata!"; }
    });

    document.getElementById('copy-bibtex-btn').addEventListener('click', () => {
        const title = document.getElementById('modal-title').innerText;
        const authors = document.getElementById('modal-authors').innerText;
        const mockBibtex = `@article{mock2026,\n  title={${title}},\n  author={${authors}},\n  journal={Nature Bio},\n  year={2026},\n  publisher={MockPublisher}\n}`;
        navigator.clipboard.writeText(mockBibtex);
        
        const btn = document.getElementById('copy-bibtex-btn');
        btn.innerText = "Kopyalandı!";
        setTimeout(() => { btn.innerText = "BibTeX Kopyala"; }, 2000);
    });

    document.getElementById('delete-article-btn').addEventListener('click', async () => {
        if(confirm('Bu makaleyi silmek istediğinize emin misiniz?')) {
            const btn = document.getElementById('delete-article-btn');
            const oldText = btn.innerText;
            btn.innerText = "Siliniyor...";
            try {
                await fetch(`/api/articles/${currentArticleId}`, { method: 'DELETE' });
                const card = document.querySelector(`.article-card[data-id='${currentArticleId}']`);
                if(card) card.remove();
                modal.classList.remove('active');
                updateCounts();
            } catch(e) {
                console.error(e);
            } finally {
                btn.innerText = oldText;
            }
        }
    });
});
