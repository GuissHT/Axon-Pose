(function initAxonPoseNavigation() {
    const sidebar = document.getElementById('main-navigation');
    const toggle = document.querySelector('.mobile-menu-toggle');
    if (!sidebar || !toggle) {
        return;
    }

    const closeMenu = () => {
        sidebar.classList.remove('is-open');
        toggle.setAttribute('aria-expanded', 'false');
    };

    toggle.addEventListener('click', () => {
        const isOpen = sidebar.classList.toggle('is-open');
        toggle.setAttribute('aria-expanded', String(isOpen));
    });

    sidebar.querySelectorAll('a').forEach((link) => {
        link.addEventListener('click', closeMenu);
    });

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
            closeMenu();
        }
    });
})();
