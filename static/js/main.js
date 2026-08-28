/* 
   Scripts globaux - GEC Ministère
*/

document.addEventListener('DOMContentLoaded', function() {
    console.log('Système de Gestion des Courriers initialisé.');

    // Gestion de la fermeture des alertes
    const closeButtons = document.querySelectorAll('.close-alert');
    closeButtons.forEach(button => {
        button.addEventListener('click', function() {
            const alert = this.parentElement;
            alert.style.opacity = '0';
            setTimeout(() => {
                alert.style.display = 'none';
            }, 300);
        });
    });
});
