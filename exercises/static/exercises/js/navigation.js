(function initAxonPoseNavigation() {
    const layout = document.querySelector('.app-layout');
    const sidebar = document.getElementById('main-navigation');
    const toggle = document.querySelector('.mobile-menu-toggle');
    if (!layout || !sidebar || !toggle) {
        return;
    }

    const setCollapsed = (collapsed) => {
        layout.classList.toggle('is-sidebar-collapsed', collapsed);
        toggle.setAttribute('aria-expanded', String(!collapsed));
        toggle.setAttribute('aria-label', collapsed ? 'Expandir menú' : 'Contraer menú');
    };

    setCollapsed(window.localStorage.getItem('axon-sidebar-collapsed') === 'true');

    toggle.addEventListener('click', () => {
        const collapsed = !layout.classList.contains('is-sidebar-collapsed');
        setCollapsed(collapsed);
        window.localStorage.setItem('axon-sidebar-collapsed', String(collapsed));
    });

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
            setCollapsed(true);
            window.localStorage.setItem('axon-sidebar-collapsed', 'true');
        }
    });
})();
