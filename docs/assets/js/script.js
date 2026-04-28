// Theme management
const getPreferredTheme = () => {
    const saved = localStorage.getItem('theme');
    if (saved) return saved;
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
};

const sunIcon = `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line></svg> Light Mode`;
const moonIcon = `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg> Dark Mode`;

const setTheme = (theme) => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
    const toggle = document.getElementById('theme-toggle');
    if (toggle) {
        toggle.innerHTML = theme === 'dark' ? sunIcon : moonIcon;
    }
};

// Apply immediately
setTheme(getPreferredTheme());

window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
    if (!localStorage.getItem('theme')) {
        setTheme(e.matches ? 'dark' : 'light');
    }
});

document.addEventListener('DOMContentLoaded', () => {
    // Theme toggle listener
    const themeToggle = document.getElementById('theme-toggle');
    if (themeToggle) {
        themeToggle.innerHTML = document.documentElement.getAttribute('data-theme') === 'dark' ? sunIcon : moonIcon;
        themeToggle.addEventListener('click', () => {
            const current = document.documentElement.getAttribute('data-theme');
            setTheme(current === 'dark' ? 'light' : 'dark');
        });
    }

    // --- Language Switcher & Auto-Detect (URL based) ---
    const langBtns = document.querySelectorAll('.lang-btn');
    
    if (langBtns.length > 0) {
        const currentPath = window.location.pathname;

        langBtns.forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                const targetLang = e.currentTarget.getAttribute('data-lang');
                localStorage.setItem('dz_lang_set', 'true');
                
                let newPath = currentPath;
                // Strip existing lang prefix
                newPath = newPath.replace(/\/zh-CN\//g, '/').replace(/\/fr\//g, '/').replace(/\/ru\//g, '/').replace(/\/es\//g, '/').replace(/\/ja\//g, '/').replace(/\/en\//g, '/');
                
                let base = newPath.startsWith('/DeepZero') ? '/DeepZero' : '';
                let pathAfterBase = newPath.substring(base.length);
                if (!pathAfterBase.startsWith('/')) pathAfterBase = '/' + pathAfterBase;
                
                newPath = base + '/' + targetLang + pathAfterBase;
                window.location.href = newPath;
            });
        });

        // Auto-detect on first visit (only on root)
        const hasVisited = localStorage.getItem('dz_lang_set');
        if (!hasVisited && (currentPath === '/DeepZero/' || currentPath === '/DeepZero/index.html' || currentPath === '/' || currentPath === '/index.html')) {
            const userLang = navigator.language || navigator.userLanguage;
            localStorage.setItem('dz_lang_set', 'true');
            
            let base = currentPath.startsWith('/DeepZero') ? '/DeepZero' : '';
            if (userLang.startsWith('fr')) {
                window.location.href = base + '/fr/';
            } else if (userLang.startsWith('zh')) {
                window.location.href = base + '/zh-CN/';
            } else if (userLang.startsWith('ru')) {
                window.location.href = base + '/ru/';
            } else if (userLang.startsWith('es')) {
                window.location.href = base + '/es/';
            } else if (userLang.startsWith('ja')) {
                window.location.href = base + '/ja/';
            } else {
                window.location.href = base + '/en/';
            }
        }
        
        // Custom Dropdown logic
        const langDropdownBtn = document.querySelector('.dropdown-btn');
        const langDropdownMenu = document.querySelector('.dropdown-menu');
        if (langDropdownBtn && langDropdownMenu) {
            const labelSpan = document.getElementById('current-lang-label');
            if (currentPath.includes('/zh-CN/')) {
                labelSpan.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path></svg> 🇨🇳 简体中文';
            } else if (currentPath.includes('/fr/')) {
                labelSpan.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path></svg> 🇫🇷 Français';
            } else if (currentPath.includes('/ru/')) {
                labelSpan.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path></svg> 🇷🇺 Русский';
            } else if (currentPath.includes('/es/')) {
                labelSpan.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path></svg> 🇪🇸 Español';
            } else if (currentPath.includes('/ja/')) {
                labelSpan.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path></svg> 🇯🇵 日本語';
            } else {
                labelSpan.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path></svg> 🇺🇸 English';
            }

            langDropdownBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                const isExpanded = langDropdownBtn.getAttribute('aria-expanded') === 'true';
                langDropdownBtn.setAttribute('aria-expanded', !isExpanded);
                langDropdownMenu.style.display = isExpanded ? 'none' : 'block';
            });

            document.addEventListener('click', () => {
                langDropdownBtn.setAttribute('aria-expanded', 'false');
                langDropdownMenu.style.display = 'none';
            });
        }
    }

    // -- Mobile sidebar toggle --
    const menuToggle = document.getElementById('menu-toggle');
    const sidebar = document.getElementById('sidebar');
    
    // Create overlay
    const overlay = document.createElement('div');
    overlay.style.position = 'fixed';
    overlay.style.top = '0';
    overlay.style.left = '0';
    overlay.style.right = '0';
    overlay.style.bottom = '0';
    overlay.style.background = 'rgba(0,0,0,0.5)';
    overlay.style.zIndex = '90';
    overlay.style.display = 'none';
    document.body.appendChild(overlay);

    if (menuToggle) {
        menuToggle.addEventListener('click', () => {
            sidebar.classList.toggle('open');
            overlay.style.display = sidebar.classList.contains('open') ? 'block' : 'none';
        });
    }

    if (overlay) {
        overlay.addEventListener('click', () => {
            sidebar.classList.remove('open');
            overlay.style.display = 'none';
        });
    }

    // -- Active sidebar link tracking on scroll --
    const sections = document.querySelectorAll('section.doc-section');
    const navLinks = document.querySelectorAll('.nav-links a');

    const observerOptions = {
        root: null,
        rootMargin: '-80px 0px -60% 0px',
        threshold: 0,
    };

    const observer = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
            if (entry.isIntersecting) {
                const id = entry.target.getAttribute('id');
                navLinks.forEach((link) => {
                    link.classList.remove('active');
                    if (link.getAttribute('href') === `#${id}`) {
                        link.classList.add('active');
                    }
                });
            }
        });
    }, observerOptions);

    sections.forEach((section) => {
        observer.observe(section);
    });

    // -- Close sidebar on link click (mobile) --
    navLinks.forEach((link) => {
        link.addEventListener('click', () => {
            if (window.innerWidth <= 768) {
                sidebar.classList.remove('open');
                overlay.style.display = 'none';
            }
        });
    });

    // -- Smooth scroll for sidebar links --
    navLinks.forEach((link) => {
        link.addEventListener('click', (e) => {
            const href = link.getAttribute('href');
            if (href && href.startsWith('#')) {
                const target = document.querySelector(href);
                if (target) {
                    e.preventDefault();
                    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    history.pushState(null, '', href);
                }
            }
        });
    });
});
