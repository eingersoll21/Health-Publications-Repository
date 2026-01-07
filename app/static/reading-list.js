/**
 * Reading List JavaScript functionality
 * Handles AJAX operations for saving, removing, and organizing publications
 */

// ============================================================================
// MODAL FUNCTIONS
// ============================================================================

function showModal(modalId) {
    document.getElementById(modalId).style.display = 'flex';
}

function hideModal(modalId) {
    document.getElementById(modalId).style.display = 'none';
}

function showCreateFolderModal() {
    document.getElementById('new-folder-name').value = '';
    document.getElementById('new-folder-description').value = '';
    showModal('create-folder-modal');
}

function showEditFolderModal(folderId, folderName, folderDescription) {
    document.getElementById('edit-folder-id').value = folderId;
    document.getElementById('edit-folder-name').value = folderName;
    document.getElementById('edit-folder-description').value = folderDescription || '';
    showModal('edit-folder-modal');
}

function showMoveModal(publicationId, currentFolderId) {
    document.getElementById('move-publication-id').value = publicationId;

    // Select the current folder
    const radioButtons = document.querySelectorAll('input[name="move-folder"]');
    radioButtons.forEach(radio => {
        const value = radio.value === 'null' ? null : parseInt(radio.value);
        radio.checked = (value === currentFolderId);
    });

    showModal('move-folder-modal');
}

function showEditNotesModal(publicationId, currentNotes) {
    document.getElementById('notes-publication-id').value = publicationId;
    document.getElementById('publication-notes').value = currentNotes || '';
    showModal('edit-notes-modal');
}

// Close modal when clicking outside
document.addEventListener('click', function(event) {
    if (event.target.classList.contains('modal')) {
        event.target.style.display = 'none';
    }
});


// ============================================================================
// FOLDER API FUNCTIONS
// ============================================================================

async function createFolder() {
    const name = document.getElementById('new-folder-name').value.trim();
    const description = document.getElementById('new-folder-description').value.trim();

    if (!name) {
        alert('Please enter a folder name');
        return;
    }

    try {
        const response = await fetch('/api/reading-folders', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, description })
        });

        const data = await response.json();

        if (data.success) {
            hideModal('create-folder-modal');

            // Check if there's a pending publication to save
            const pendingPublicationId = sessionStorage.getItem('pendingSavePublicationId');
            if (pendingPublicationId && data.folder && data.folder.id) {
                sessionStorage.removeItem('pendingSavePublicationId');
                // Save the publication to the newly created folder
                await savePublication(parseInt(pendingPublicationId), data.folder.id);
            }

            // Only reload if we're on the reading list page
            if (window.location.pathname === '/reading-list') {
                window.location.reload();
            }
        } else {
            alert(data.error || 'Failed to create folder');
        }
    } catch (error) {
        console.error('Error creating folder:', error);
        alert('An error occurred. Please try again.');
    }
}

async function updateFolder() {
    const folderId = document.getElementById('edit-folder-id').value;
    const name = document.getElementById('edit-folder-name').value.trim();
    const description = document.getElementById('edit-folder-description').value.trim();

    if (!name) {
        alert('Please enter a folder name');
        return;
    }

    try {
        const response = await fetch(`/api/reading-folders/${folderId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, description })
        });

        const data = await response.json();

        if (data.success) {
            hideModal('edit-folder-modal');
            window.location.reload();
        } else {
            alert(data.error || 'Failed to update folder');
        }
    } catch (error) {
        console.error('Error updating folder:', error);
        alert('An error occurred. Please try again.');
    }
}

async function deleteFolder() {
    const folderId = document.getElementById('edit-folder-id').value;

    if (!confirm('Delete this folder? Publications in this folder will be moved to Unfiled.')) {
        return;
    }

    try {
        const response = await fetch(`/api/reading-folders/${folderId}`, {
            method: 'DELETE'
        });

        const data = await response.json();

        if (data.success) {
            hideModal('edit-folder-modal');
            window.location.href = '/reading-list';
        } else {
            alert(data.error || 'Failed to delete folder');
        }
    } catch (error) {
        console.error('Error deleting folder:', error);
        alert('An error occurred. Please try again.');
    }
}


// ============================================================================
// PUBLICATION API FUNCTIONS
// ============================================================================

async function savePublication(publicationId, folderId = null) {
    try {
        const response = await fetch('/api/saved-publications', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ publication_id: publicationId, folder_id: folderId })
        });

        const data = await response.json();

        if (data.success) {
            // Update UI to show saved state
            updateBookmarkButton(publicationId, true, folderId);
            return true;
        } else {
            if (data.error !== 'Publication already saved') {
                alert(data.error || 'Failed to save publication');
            }
            return false;
        }
    } catch (error) {
        console.error('Error saving publication:', error);
        alert('An error occurred. Please try again.');
        return false;
    }
}

async function removeFromReadingList(publicationId) {
    if (!confirm('Remove this publication from your reading list?')) {
        return;
    }

    try {
        const response = await fetch(`/api/saved-publications/${publicationId}`, {
            method: 'DELETE'
        });

        const data = await response.json();

        if (data.success) {
            // Remove the card from the page
            const card = document.querySelector(`[data-publication-id="${publicationId}"]`);
            if (card) {
                card.remove();
            }
            // Update bookmark button if on browse/home page
            updateBookmarkButton(publicationId, false, null);
        } else {
            alert(data.error || 'Failed to remove publication');
        }
    } catch (error) {
        console.error('Error removing publication:', error);
        alert('An error occurred. Please try again.');
    }
}

async function moveToFolder() {
    const publicationId = document.getElementById('move-publication-id').value;
    const selectedRadio = document.querySelector('input[name="move-folder"]:checked');

    if (!selectedRadio) {
        alert('Please select a folder');
        return;
    }

    const folderId = selectedRadio.value === 'null' ? null : parseInt(selectedRadio.value);

    try {
        const response = await fetch(`/api/saved-publications/${publicationId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ folder_id: folderId })
        });

        const data = await response.json();

        if (data.success) {
            hideModal('move-folder-modal');
            window.location.reload();
        } else {
            alert(data.error || 'Failed to move publication');
        }
    } catch (error) {
        console.error('Error moving publication:', error);
        alert('An error occurred. Please try again.');
    }
}

async function toggleReadStatus(publicationId, setRead) {
    try {
        const response = await fetch(`/api/saved-publications/${publicationId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ is_read: setRead })
        });

        const data = await response.json();

        if (data.success) {
            window.location.reload();
        } else {
            alert(data.error || 'Failed to update read status');
        }
    } catch (error) {
        console.error('Error updating read status:', error);
        alert('An error occurred. Please try again.');
    }
}

async function saveNotes() {
    const publicationId = document.getElementById('notes-publication-id').value;
    const notes = document.getElementById('publication-notes').value.trim();

    try {
        const response = await fetch(`/api/saved-publications/${publicationId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ notes: notes })
        });

        const data = await response.json();

        if (data.success) {
            hideModal('edit-notes-modal');
            window.location.reload();
        } else {
            alert(data.error || 'Failed to save notes');
        }
    } catch (error) {
        console.error('Error saving notes:', error);
        alert('An error occurred. Please try again.');
    }
}


// ============================================================================
// BOOKMARK BUTTON FUNCTIONS (for browse/home pages)
// ============================================================================

function updateBookmarkButton(publicationId, isSaved, folderId) {
    const btn = document.querySelector(`.bookmark-btn[data-publication-id="${publicationId}"]`);
    if (!btn) return;

    if (isSaved) {
        btn.classList.add('saved');
        btn.innerHTML = '&#9733;'; // Filled star
        btn.title = 'Saved to Reading List';
    } else {
        btn.classList.remove('saved');
        btn.innerHTML = '&#9734;'; // Empty star
        btn.title = 'Save to Reading List';
    }
}

async function toggleSavePublication(publicationId, button) {
    const isSaved = button.classList.contains('saved');

    if (isSaved) {
        // Show remove confirmation or dropdown
        if (confirm('Remove from reading list?')) {
            await removeFromReadingList(publicationId);
        }
    } else {
        // Show save dropdown
        showSaveDropdown(publicationId, button);
    }
}

function showSaveDropdown(publicationId, button) {
    // Close any existing dropdowns
    document.querySelectorAll('.save-dropdown').forEach(d => d.remove());

    // Fetch folders and show dropdown
    fetch('/api/reading-folders')
        .then(response => response.json())
        .then(data => {
            if (!data.success) return;

            const dropdown = document.createElement('div');
            dropdown.className = 'save-dropdown';

            let html = '<div class="save-dropdown-content">';
            html += `<button class="save-option" onclick="quickSave(${publicationId})">&#9734; Quick Save (Unfiled)</button>`;

            if (data.folders.length > 0) {
                html += '<div class="save-dropdown-divider"></div>';
                data.folders.forEach(folder => {
                    html += `<button class="save-option" onclick="saveToFolder(${publicationId}, ${folder.id})">&#128193; ${escapeHtml(folder.name)}</button>`;
                });
            }

            html += '<div class="save-dropdown-divider"></div>';
            html += `<button class="save-option" onclick="showCreateFolderAndSave(${publicationId})">+ Create new folder</button>`;
            html += '</div>';

            dropdown.innerHTML = html;

            // Position the dropdown
            const rect = button.getBoundingClientRect();
            dropdown.style.position = 'fixed';
            dropdown.style.top = (rect.bottom + 5) + 'px';
            dropdown.style.left = rect.left + 'px';

            document.body.appendChild(dropdown);

            // Close when clicking outside
            setTimeout(() => {
                document.addEventListener('click', function closeDropdown(e) {
                    if (!dropdown.contains(e.target) && e.target !== button) {
                        dropdown.remove();
                        document.removeEventListener('click', closeDropdown);
                    }
                });
            }, 0);
        })
        .catch(error => {
            console.error('Error fetching folders:', error);
            // Fallback to quick save
            savePublication(publicationId, null);
        });
}

async function quickSave(publicationId) {
    document.querySelectorAll('.save-dropdown').forEach(d => d.remove());
    await savePublication(publicationId, null);
}

async function saveToFolder(publicationId, folderId) {
    document.querySelectorAll('.save-dropdown').forEach(d => d.remove());
    await savePublication(publicationId, folderId);
}

function showCreateFolderAndSave(publicationId) {
    document.querySelectorAll('.save-dropdown').forEach(d => d.remove());
    // Store publication ID to save after folder creation
    sessionStorage.setItem('pendingSavePublicationId', publicationId);
    showCreateFolderModal();
}

// Helper function to escape HTML
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}


// ============================================================================
// INITIALIZATION
// ============================================================================

document.addEventListener('DOMContentLoaded', function() {
    // Load saved status for publication cards on browse/home pages
    const bookmarkBtns = document.querySelectorAll('.bookmark-btn');
    if (bookmarkBtns.length > 0) {
        const publicationIds = Array.from(bookmarkBtns).map(btn => btn.dataset.publicationId);
        loadSavedStatus(publicationIds);
    }
});

async function loadSavedStatus(publicationIds) {
    if (publicationIds.length === 0) return;

    try {
        const idsParam = publicationIds.map(id => `ids=${id}`).join('&');
        const response = await fetch(`/api/publication-saved-status?${idsParam}`);
        const data = await response.json();

        if (data.success) {
            Object.keys(data.saved).forEach(pubId => {
                updateBookmarkButton(pubId, true, data.saved[pubId].folder_id);
            });
        }
    } catch (error) {
        console.error('Error loading saved status:', error);
    }
}
