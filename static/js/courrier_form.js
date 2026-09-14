document.addEventListener('DOMContentLoaded', function () {
    const fileInput = document.getElementById('id_fichier_scan');
    const fileDisplay = document.getElementById('file-name-display');
    const fileNameText = document.getElementById('file-name-text');
    const dropZone = document.getElementById('file-drop-zone');

    function showSelectedFile(file) {
        if (!file || !fileDisplay || !fileNameText) {
            return;
        }
        fileNameText.textContent = file.name + ' (' + (file.size / 1024).toFixed(1) + ' Ko)';
        fileDisplay.style.display = 'block';
    }

    if (dropZone && fileInput) {
        dropZone.addEventListener('click', function () {
            fileInput.click();
        });
    }

    if (fileInput) {
        fileInput.addEventListener('change', function () {
            if (this.files && this.files.length > 0) {
                showSelectedFile(this.files[0]);
            }
        });
    }

    if (dropZone) {
        dropZone.addEventListener('dragover', function (event) {
            event.preventDefault();
            dropZone.classList.add('dragover');
        });

        dropZone.addEventListener('dragleave', function () {
            dropZone.classList.remove('dragover');
        });

        dropZone.addEventListener('drop', function (event) {
            event.preventDefault();
            dropZone.classList.remove('dragover');
            if (event.dataTransfer.files.length > 0 && fileInput) {
                fileInput.files = event.dataTransfer.files;
                showSelectedFile(event.dataTransfer.files[0]);
            }
        });
    }

    const dateInput = document.getElementById('id_date_arrivee');
    if (dateInput && !dateInput.value) {
        const now = new Date();
        now.setSeconds(0, 0);
        dateInput.value = now.toISOString().slice(0, 16);
    }
});
