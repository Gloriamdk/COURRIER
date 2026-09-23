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
            
            // Synchroniser l'éditeur à chaque modification pour garder la prévisualisation à jour
            editor.model.document.on('change:data', function() {
                if (!currentValidationInput) {
                    updatePreview();
                }
            });

            updatePreview();
        }).catch(error => {
            console.error(error);
        });
    }

    window.openEditorModal = function() {
        currentValidationInput = null;
        document.getElementById('word-editor-modal').style.display = 'flex';
        if (globalEditor) { globalEditor.focus(); }
    };

    var currentValidationInput = null;

    window.openEditorModalForValidation = function(id) {
        currentValidationInput = document.getElementById('lettre_html_' + id);
        var originalContentDiv = document.getElementById('original_lettre_content_' + id);
        var originalContent = originalContentDiv ? originalContentDiv.innerHTML : '';
        
        document.getElementById('word-editor-modal').style.display = 'flex';
        if (globalEditor) {
            var contentToLoad = currentValidationInput.value || originalContent;
            globalEditor.setData(contentToLoad);
            globalEditor.focus();
        }
    };

    window.closeEditorModal = function() {
        document.getElementById('word-editor-modal').style.display = 'none';
        currentValidationInput = null;
    };

    window.saveEditorModal = function() {
        if (globalEditor) {
            var html = globalEditor.getData();
            if (currentValidationInput) {
                currentValidationInput.value = html;
            } else if (hiddenInput) {
                hiddenInput.value = html;
                updatePreview();
            }
        }
        closeEditorModal();
    };

    function updatePreview() {
        if (hiddenInput && previewDiv) {
            var content = hiddenInput.value.trim();
            if (content) {
                // Toujours utiliser innerHTML pour rendre le HTML de l'éditeur correctement
                previewDiv.innerHTML = content;
                previewDiv.style.fontStyle = 'normal';
                previewDiv.style.color = 'inherit';
            } else {
                previewDiv.innerHTML = '<i style="color:var(--text-muted);">Le texte de la lettre s\'affichera ici...</i>';
            }
        }
    }
    
    // Synchroniser l'éditeur au moment de la soumission du formulaire Agent
    var form = document.getElementById('form-reponse-agent');
    if(form && hiddenInput) {
        form.addEventListener('submit', function(e) {
            if (globalEditor && !currentValidationInput) {
                hiddenInput.value = globalEditor.getData();
            }
        });
    }
});

