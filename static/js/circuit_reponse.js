// === Éditeur CKEditor — Circuit de réponse ===
// Initialisation PARESSEUSE : l'éditeur n'est créé qu'au premier clic sur le bouton.
// Cela évite de charger ~5 Mo de JavaScript inutilement au chargement de la page.

var globalEditor      = null;   // Instance CKEditor (créée une seule fois)
var editorInitPromise = null;   // Promise en cours d'initialisation
var currentValidationInput = null;  // Champ hidden à remplir au "Enregistrer"

// Lance ou retourne la création de l'éditeur (appel idempotent)
function getOrCreateEditor() {
    if (globalEditor) {
        return Promise.resolve(globalEditor);
    }
    if (editorInitPromise) {
        return editorInitPromise;
    }

    var editorBody = document.querySelector('#word-editor-body');
    if (!editorBody) {
        return Promise.reject(new Error('Element #word-editor-body introuvable.'));
    }

    if (typeof CKEDITOR === 'undefined') {
        return Promise.reject(new Error('CKEditor non chargé.'));
    }

    editorInitPromise = CKEDITOR.DecoupledEditor.create(editorBody, {
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
    }).then(function(editor) {
        globalEditor = editor;
        var toolbarContainer = document.querySelector('#word-toolbar-container');
        if (toolbarContainer) {
            toolbarContainer.appendChild(editor.ui.view.toolbar.element);
        }
        return editor;
    }).catch(function(err) {
        editorInitPromise = null; // Permettre une nouvelle tentative
        console.error('CKEditor init error:', err);
        throw err;
    });

    return editorInitPromise;
}

// Ouvre la modale, puis initialise/met à jour l'éditeur
function _openModal(validationInput, contentToLoad) {
    currentValidationInput = validationInput || null;

    var modal = document.getElementById('word-editor-modal');
    if (!modal) { return; }

    // 1. Montrer la modale immédiatement (l'éditeur apparaît en cours de chargement)
    modal.style.display = 'flex';

    // 2. Charger l'éditeur (ou récupérer l'instance existante)
    getOrCreateEditor().then(function(editor) {
        editor.setData(contentToLoad || '');
        editor.focus();

        // Si l'agent : aussi mettre à jour la prévisualisation
        if (!currentValidationInput) {
            _updatePreview(editor.getData());
            editor.model.document.on('change:data', function() {
                if (!currentValidationInput) {
                    _updatePreview(editor.getData());
                }
            });
        }
    }).catch(function(err) {
        console.error(err);
        alert("L'éditeur est en cours de téléchargement, ou une erreur réseau est survenue. Veuillez patienter quelques secondes puis réessayer.");
    });
}

// Ouverture pour l'Agent
window.openEditorModal = function() {
    var hiddenInput = document.querySelector('#id_observation_reponse');
    var existingContent = hiddenInput ? hiddenInput.value : '';
    _openModal(null, existingContent);
};

// Ouverture pour la hiérarchie (Directeur, SG, DC, Secrétaires)
window.openEditorModalForValidation = function(id) {
    var input       = document.getElementById('lettre_html_' + id);
    var originalDiv = document.getElementById('original_lettre_content_' + id);
    var content     = (input && input.value) ? input.value
                    : (originalDiv ? originalDiv.innerHTML : '');
    _openModal(input, content);
};

window.closeEditorModal = function() {
    var modal = document.getElementById('word-editor-modal');
    if (modal) { modal.style.display = 'none'; }
    currentValidationInput = null;
};

window.saveEditorModal = function() {
    if (!globalEditor) { closeEditorModal(); return; }

    var html = globalEditor.getData();

    if (currentValidationInput) {
        // Mode hiérarchie : stocker dans le champ hidden du formulaire de validation
        currentValidationInput.value = html;
    } else {
        // Mode agent : stocker dans le champ caché et prévisualiser
        var hiddenInput = document.querySelector('#id_observation_reponse');
        if (hiddenInput) {
            hiddenInput.value = html;
            _updatePreview(html);
        }
    }
    closeEditorModal();
};

function _updatePreview(html) {
    var previewDiv = document.querySelector('#editor-preview');
    if (!previewDiv) { return; }
    if (html && html.trim()) {
        previewDiv.innerHTML = html;
        previewDiv.style.fontStyle = 'normal';
        previewDiv.style.color = 'inherit';
    } else {
        previewDiv.innerHTML = '<i style="color:var(--text-muted);">Le texte de la lettre s\'affichera ici...</i>';
    }
}

// Synchroniser l'éditeur avant soumission du formulaire Agent
document.addEventListener('DOMContentLoaded', function() {
    var form = document.getElementById('form-reponse-agent');
    if (form) {
        form.addEventListener('submit', function() {
            if (globalEditor && !currentValidationInput) {
                var hiddenInput = document.querySelector('#id_observation_reponse');
                if (hiddenInput) { hiddenInput.value = globalEditor.getData(); }
            }
        });
    }
});
