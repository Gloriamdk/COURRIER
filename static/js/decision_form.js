document.addEventListener("DOMContentLoaded", function() {
    var editorBody = document.getElementById('word-editor-body');
    var previewDiv = document.getElementById('editor-preview');
    var hiddenInput = document.getElementById('lettre_html');
    var originalContent = document.getElementById('original_lettre_content');

    if (!editorBody) return;

    // Charger le contenu original de la lettre validée
    if (originalContent) {
        // Sécurisation XSS : Assainir le contenu original avant injection dans l'éditeur
        if (window.DOMPurify) {
            // Utiliser DOMPurify pour assainir, puis injecter de manière sécurisée
            editorBody.innerHTML = DOMPurify.sanitize(originalContent.innerHTML);
        } else {
            editorBody.textContent = originalContent.textContent;
        }
    }

    CKEDITOR.DecoupledEditor.create(editorBody, {
        toolbar: {
            items: [
                'heading', '|',
                'fontSize', 'fontFamily', 'fontColor', 'fontBackgroundColor', '|',
                'bold', 'italic', 'underline', 'strikethrough', '|',
                'alignment', '|',
                'numberedList', 'bulletedList', '|',
                'outdent', 'indent', '|',
                'insertTable', 'link', 'imageInsert', '|',
                'undo', 'redo'
            ],
            shouldNotGroupWhenFull: true
        },
        image: {
            toolbar: ['imageStyle:inline', 'imageStyle:block', 'imageStyle:side', '|', 'imageTextAlternative']
        },
        placeholder: 'Le contenu de la lettre validée apparaît ici. Ajoutez votre signature électronique (image)...',
        removePlugins: [
            'CKBox', 'CKFinder', 'EasyImage', 'RealTimeCollaborativeComments',
            'RealTimeCollaborativeTrackChanges', 'RealTimeCollaborativeRevisionHistory',
            'PresenceList', 'Comments', 'TrackChanges', 'TrackChangesData',
            'RevisionHistory', 'Pagination', 'WProofreader', 'MathType',
            'SlashCommand', 'Template', 'DocumentOutline', 'FormatPainter', 'TableOfContents',
            'PasteFromOfficeEnhanced'
        ]
    }).then(function(editor) {
        globalEditor = editor;
        var toolbarContainer = document.getElementById('word-toolbar-container');
        toolbarContainer.appendChild(editor.ui.view.toolbar.element);
    }).catch(function(error) {
        console.error('CKEditor init error:', error);
    });

    // Fonctions globales pour le modal
    window.openEditorModal = function() {
        document.getElementById('word-editor-modal').style.display = 'flex';
        if (globalEditor) { globalEditor.focus(); }
    };

    window.closeEditorModal = function() {
        document.getElementById('word-editor-modal').style.display = 'none';
    };

    window.saveEditorModal = function() {
        if (globalEditor && hiddenInput) {
            var html = globalEditor.getData();
            hiddenInput.value = html;

            // Mettre à jour l'aperçu
            if (previewDiv) {
                if (window.DOMPurify) {
                    previewDiv.innerHTML = DOMPurify.sanitize(html);
                } else {
                    previewDiv.textContent = html;
                }
                previewDiv.style.display = 'block';
            }
        }
        closeEditorModal();
    };

    var form = document.querySelector('form.form-card');
    if (form && hiddenInput) {
        form.addEventListener('submit', function(e) {
            if (globalEditor && hiddenInput.value === '') {
                hiddenInput.value = globalEditor.getData();
            }
        });
    }
});
