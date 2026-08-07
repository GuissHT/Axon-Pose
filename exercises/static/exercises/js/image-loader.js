/*
   Cargador de imagenes: muestra imagen real si existe en static, si no deja placeholder con mensaje.
*/
(function initAxonPoseImageLoader() {
    const slots = document.querySelectorAll('[data-image-slot]');
    if (!slots.length) {
        return;
    }

    slots.forEach((slot) => {
        const img = slot.querySelector('img[data-image-autoload]');
        const placeholder = slot.querySelector('.image-placeholder');
        if (!img || !placeholder) {
            return;
        }

        const showImage = () => {
            img.classList.add('is-visible');
            placeholder.classList.add('is-hidden');
        };

        const showPlaceholder = () => {
            img.classList.remove('is-visible');
            placeholder.classList.remove('is-hidden');
        };

        img.addEventListener('load', () => {
            if (img.naturalWidth > 0) {
                showImage();
            } else {
                showPlaceholder();
            }
        });

        img.addEventListener('error', showPlaceholder);

        if (img.complete && img.naturalWidth > 0) {
            showImage();
        } else {
            showPlaceholder();
        }
    });
})();
