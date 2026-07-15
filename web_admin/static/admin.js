(() => {
    const allowedTags = new Set(['b','strong','i','em','u','ins','s','strike','del','span','tg-spoiler','a','code','pre','blockquote']);

    const safeUrl = (value) => {
        try {
            const url = new URL(value, window.location.origin);
            return ['http:', 'https:'].includes(url.protocol) || (url.protocol === 'tg:' && value.startsWith('tg://user?id='));
        } catch (_) { return false; }
    };

    const sanitizeTelegramHtml = (source) => {
        const parsed = new DOMParser().parseFromString(source, 'text/html');
        const output = document.createDocumentFragment();
        const copy = (node, target, parentTag = '') => {
            if (node.nodeType === Node.TEXT_NODE) { target.appendChild(document.createTextNode(node.textContent)); return; }
            if (node.nodeType !== Node.ELEMENT_NODE) return;
            const tag = node.tagName.toLowerCase();
            if (!allowedTags.has(tag)) { node.childNodes.forEach((child) => copy(child, target, parentTag)); return; }
            const clean = document.createElement(tag);
            if (tag === 'a' && safeUrl(node.getAttribute('href') || '')) clean.setAttribute('href', node.getAttribute('href'));
            if (tag === 'span' && node.getAttribute('class') === 'tg-spoiler') clean.className = 'tg-spoiler';
            if (tag === 'blockquote' && node.hasAttribute('expandable')) clean.setAttribute('expandable', '');
            if (tag === 'code' && parentTag === 'pre' && /^language-[\w+.#-]+$/.test(node.getAttribute('class') || '')) clean.className = node.getAttribute('class');
            node.childNodes.forEach((child) => copy(child, clean, tag));
            target.appendChild(clean);
        };
        parsed.body.childNodes.forEach((node) => copy(node, output));
        return output;
    };

    const composer = document.querySelector('[data-composer]');
    if (composer) {
        const message = composer.querySelector('[data-message-input]');
        const media = composer.querySelector('[data-media-input]');
        const preview = composer.querySelector('[data-message-preview]');
        const mediaPreview = composer.querySelector('[data-media-preview]');
        const counter = composer.querySelector('[data-character-count]');
        const limit = composer.querySelector('[data-character-limit]');
        const buttonsList = composer.querySelector('[data-buttons-list]');
        const buttonTemplate = composer.querySelector('[data-button-template]');
        const buttonsPreview = composer.querySelector('[data-buttons-preview]');

        const updateButtons = () => {
            buttonsPreview.replaceChildren();
            buttonsList.querySelectorAll('.button-row').forEach((row) => {
                const text = row.querySelector('[name="button_text"]').value.trim();
                if (!text) return;
                const item = document.createElement('span'); item.className = 'telegram-button'; item.textContent = text; buttonsPreview.appendChild(item);
            });
        };
        const addButton = () => {
            if (buttonsList.children.length >= 8) return;
            const fragment = buttonTemplate.content.cloneNode(true);
            const row = fragment.querySelector('.button-row');
            row.querySelector('[data-remove-button]').addEventListener('click', () => { row.remove(); updateButtons(); });
            row.querySelectorAll('input,select').forEach((input) => input.addEventListener('input', updateButtons));
            buttonsList.appendChild(fragment); updateButtons();
        };
        composer.querySelector('[data-add-button]').addEventListener('click', addButton);
        addButton();

        const updatePreview = () => {
            const source = (message.value || 'Текст сообщения появится здесь.').replaceAll('[Имя]', 'Анна');
            const clean = sanitizeTelegramHtml(source);
            const textProbe = document.createElement('div'); textProbe.appendChild(clean.cloneNode(true));
            preview.replaceChildren(clean);
            counter.textContent = textProbe.textContent.length.toLocaleString('ru-RU');
            const max = media.files.length ? 1024 : 4096;
            limit.textContent = max.toLocaleString('ru-RU');
            counter.parentElement.classList.toggle('limit-warning', textProbe.textContent.length > max);
        };
        message.addEventListener('input', updatePreview);
        media.addEventListener('change', () => {
            mediaPreview.replaceChildren();
            const file = media.files[0];
            if (file) {
                const node = file.type.startsWith('video/') ? document.createElement('video') : document.createElement('img');
                node.src = URL.createObjectURL(file); if (node.tagName === 'VIDEO') node.controls = true; mediaPreview.appendChild(node);
            }
            updatePreview();
        });
        composer.querySelectorAll('[data-tag]').forEach((button) => button.addEventListener('click', () => {
            const tag = button.dataset.tag; const start = message.selectionStart; const end = message.selectionEnd;
            const selected = message.value.slice(start, end) || 'текст';
            message.setRangeText(`<${tag}>${selected}</${tag}>`, start, end, 'select'); message.dispatchEvent(new Event('input'));
        }));
        composer.querySelector('[data-link]').addEventListener('click', () => {
            const start = message.selectionStart; const end = message.selectionEnd; const selected = message.value.slice(start, end) || 'ссылка';
            message.setRangeText(`<a href="https://example.ru">${selected}</a>`, start, end, 'select'); message.dispatchEvent(new Event('input'));
        });
        updatePreview();
    }

    document.querySelectorAll('[data-confirm]').forEach((form) => form.addEventListener('submit', (event) => {
        if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    }));

    const progress = document.querySelector('[data-broadcast-progress]');
    if (progress && progress.dataset.active === 'true') {
        const poll = async () => {
            try {
                const response = await fetch(progress.dataset.statusUrl, {credentials:'same-origin', headers:{Accept:'application/json'}});
                if (!response.ok) return;
                const data = await response.json();
                document.querySelector('[data-field="status-label"]').textContent = data.status_label;
                progress.querySelector('[data-field="processed"]').textContent = data.processed_count;
                progress.querySelector('[data-field="success"]').textContent = data.success_count;
                progress.querySelector('[data-field="errors"]').textContent = data.error_count;
                progress.querySelector('[data-field="skipped"]').textContent = data.skipped_count;
                progress.querySelector('[data-field="progress-bar"]').style.width = `${data.progress}%`;
                if (['completed','completed_with_errors','cancelled','failed'].includes(data.status)) { window.setTimeout(() => window.location.reload(), 500); return; }
                window.setTimeout(poll, 1500);
            } catch (_) { window.setTimeout(poll, 3000); }
        };
        window.setTimeout(poll, 600);
    }
})();
