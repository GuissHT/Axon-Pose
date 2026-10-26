(function initAxonPoseToasts() {
    const toastElements = document.querySelectorAll('.auto-dismiss-toast');
    if (!toastElements.length || typeof bootstrap === 'undefined') {
        return;
    }

    toastElements.forEach((toastElement) => {
        const toast = new bootstrap.Toast(toastElement, { delay: 7000 });
        toast.show();
    });
})();
