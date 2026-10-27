/*
   Botón "ojito" para ver u ocultar la contraseña mientras se escribe (login y registros).
   Envuelve cada campo de contraseña visible en un input-group de Bootstrap; no cambia el
   nombre ni el valor del campo, así que el formulario se envía igual que antes.
*/
(function initPasswordToggles() {
    const iconShow = 'fa-eye';
    const iconHide = 'fa-eye-slash';

    function addToggle(input) {
        if (input.dataset.passwordToggle === 'on') return;
        if (input.getAttribute('aria-hidden') === 'true' || input.style.display === 'none') return;
        input.dataset.passwordToggle = 'on';
        input.classList.add('form-control');

        const group = document.createElement('div');
        group.className = 'input-group password-field';
        input.parentNode.insertBefore(group, input);
        group.appendChild(input);

        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'btn password-toggle';
        button.setAttribute('aria-label', 'Mostrar contraseña');
        button.setAttribute('aria-pressed', 'false');
        button.title = 'Mostrar contraseña';
        const icon = document.createElement('i');
        icon.className = `fas ${iconShow}`;
        icon.setAttribute('aria-hidden', 'true');
        button.appendChild(icon);
        group.appendChild(button);

        button.addEventListener('click', () => {
            const visible = input.type === 'password';
            input.type = visible ? 'text' : 'password';
            icon.classList.toggle(iconShow, !visible);
            icon.classList.toggle(iconHide, visible);
            const label = visible ? 'Ocultar contraseña' : 'Mostrar contraseña';
            button.setAttribute('aria-label', label);
            button.setAttribute('aria-pressed', String(visible));
            button.title = label;
            input.focus();
        });
    }

    function run() {
        document.querySelectorAll('input[type="password"]').forEach(addToggle);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', run);
    } else {
        run();
    }
})();
