document.addEventListener("DOMContentLoaded", function() {
    var editorBody = document.querySelector('#word-editor-body');
    var previewDiv = document.querySelector('#editor-preview');
    var hiddenInput = document.querySelector('#id_observation_reponse');

    if (editorBody) {
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
            list: {
                properties: { styles: true, startIndex: true, reversed: true }
            },
            placeholder: 'Rédigez la lettre de réponse ici...',
            removePlugins: [
                'CKBox', 'CKFinder', 'EasyImage', 'RealTimeCollaborativeComments',
                'RealTimeCollaborativeTrackChanges', 'RealTimeCollaborativeRevisionHistory',
                'PresenceList', 'Comments', 'TrackChanges', 'TrackChangesData',
                'RevisionHistory', 'Pagination', 'WProofreader', 'MathType',
                'SlashCommand', 'Template', 'DocumentOutline', 'FormatPainter', 'TableOfContents',
                'PasteFromOfficeEnhanced'
            ]
        }).then(editor => {
            globalEditor = editor;
            const toolbarContainer = document.querySelector('#word-toolbar-container');
            toolbarContainer.appendChild(editor.ui.view.toolbar.element);
            
            updatePreview();
        }).catch(error => {
            console.error(error);
        });
    }

    window.openEditorModal = function() {
        document.getElementById('word-editor-modal').style.display = 'flex';
        if (globalEditor) { globalEditor.focus(); }
    };

    window.closeEditorModal = function() {
        document.getElementById('word-editor-modal').style.display = 'none';
    };

    window.saveEditorModal = function() {
        if (globalEditor) {
            var html = globalEditor.getData();
            hiddenInput.value = html;
            updatePreview();
        }
        closeEditorModal();
    };

    function updatePreview() {
        if (hiddenInput && previewDiv) {
            var content = hiddenInput.value.trim();
            if (content) {
                if (window.DOMPurify) {
                    previewDiv.innerHTML = DOMPurify.sanitize(content);
                } else {
                    previewDiv.textContent = content;
                }
                previewDiv.style.fontStyle = 'normal';
                previewDiv.style.color = 'inherit';
            } else {
                // Remplacement sécurisé pour le placeholder
                previewDiv.textContent = "";
                var em = document.createElement('i');
                em.textContent = "Le texte de la lettre s'affichera ici...";
                previewDiv.appendChild(em);
                previewDiv.style.fontStyle = 'italic';
                previewDiv.style.color = 'var(--text-muted)';
            }
        }
    }
    
    var form = document.getElementById('form-reponse-agent');
    if(form && hiddenInput) {
        form.addEventListener('submit', function(e) {
            if (globalEditor) {
                hiddenInput.value = globalEditor.getData();
            }
        });
    }
});
