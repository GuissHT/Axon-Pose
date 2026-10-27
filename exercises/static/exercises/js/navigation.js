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

    // En pantallas angostas (celular) el menú siempre empieza cerrado para no tapar el contenido;
    // en computadora se respeta lo último que eligió la persona.
    let saved = null;
    try {
        saved = window.localStorage.getItem('axon-sidebar-collapsed');
    } catch (error) {
        saved = null;
    }
    setCollapsed(window.matchMedia('(max-width: 768px)').matches || saved === 'true');

    toggle.addEventListener('click', () => {
        const collapsed = !layout.classList.contains('is-sidebar-collapsed');
        setCollapsed(collapsed);
        try { window.localStorage.setItem('axon-sidebar-collapsed', String(collapsed)); } catch (error) { /* sin almacenamiento */ }
    });

    // En celular, tocar el contenido cierra el menú abierto (sin guardar la preferencia).
    const main = document.getElementById('main-content');
    if (main) {
        main.addEventListener('click', () => {
            if (window.matchMedia('(max-width: 992px)').matches && !layout.classList.contains('is-sidebar-collapsed')) {
                setCollapsed(true);
            }
        });
    }

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
            setCollapsed(true);
            try { window.localStorage.setItem('axon-sidebar-collapsed', 'true'); } catch (error) { /* sin almacenamiento */ }
        }
    });
})();
