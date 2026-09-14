document.addEventListener('DOMContentLoaded', function () {
    const toggleBtn = document.getElementById('togglePassword');
    const wrapper = document.querySelector('.input-wrapper');
    const passwordInput = wrapper ? wrapper.querySelector('input') : null;
    const eyeIcon = document.getElementById('eye-icon');
    const eyeOffIcon = document.getElementById('eye-off-icon');

    if (toggleBtn && passwordInput && eyeIcon && eyeOffIcon) {
        toggleBtn.addEventListener('click', function (event) {
            event.preventDefault();
            const isHidden = passwordInput.type === 'password';
            passwordInput.type = isHidden ? 'text' : 'password';
            eyeIcon.style.display = isHidden ? 'none' : 'block';
            eyeOffIcon.style.display = isHidden ? 'block' : 'none';
        });
    }
});
