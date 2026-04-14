(() => {
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';

  function showToast(message, level = 'success') {
    let container = document.querySelector('.admin-toast-container');
    if (!container) {
      container = document.createElement('div');
      container.className = 'admin-toast-container';
      document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    toast.className = `alert alert-${level} shadow-sm py-2 px-3 mb-2`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
      toast.remove();
    }, 2600);
  }

  async function postJson(url, payload = null) {
    const options = {
      method: 'POST',
      headers: {
        'X-CSRFToken': csrfToken,
      },
    };
    if (payload) {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(payload);
    }

    const res = await fetch(url, options);
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.success === false) {
      throw new Error(data.error || 'Request failed');
    }
    return data;
  }

  function initBlogListingActions() {
    const duplicateButtons = document.querySelectorAll('.js-duplicate-post');
    duplicateButtons.forEach((button) => {
      button.addEventListener('click', async () => {
        button.disabled = true;
        try {
          const data = await postJson(button.dataset.url);
          showToast('Post duplicated successfully.', 'success');
          if (data.redirect_url) {
            window.location.href = data.redirect_url;
          }
        } catch (error) {
          showToast(error.message || 'Could not duplicate post.', 'danger');
        } finally {
          button.disabled = false;
        }
      });
    });

    function initToggle(selector) {
      document.querySelectorAll(selector).forEach((button) => {
        button.addEventListener('click', async () => {
          try {
            const data = await postJson(button.dataset.url);
            const isActive = Boolean(data.is_featured ?? data.is_pinned);
            button.classList.toggle('is-active', isActive);
            const icon = button.querySelector('i');
            if (icon) {
              const filled = icon.className.includes('-fill');
              if (isActive && !filled) {
                icon.className = `${icon.className}-fill`;
              } else if (!isActive && filled) {
                icon.className = icon.className.replace('-fill', '');
              }
            }
          } catch (error) {
            showToast(error.message || 'Toggle failed.', 'danger');
          }
        });
      });
    }

    initToggle('.js-toggle-featured');
    initToggle('.js-toggle-pinned');

    const deleteModal = document.getElementById('deletePostModal');
    const deleteForm = document.getElementById('deletePostForm');
    const deleteTitle = document.getElementById('deletePostTitle');
    const hardDeleteInput = document.getElementById('hardDeleteInput');

    if (deleteModal && deleteForm && deleteTitle) {
      document.querySelectorAll('.js-delete-post').forEach((button) => {
        button.addEventListener('click', () => {
          deleteForm.action = button.dataset.deleteUrl;
          deleteTitle.textContent = button.dataset.postTitle || 'this post';
          if (hardDeleteInput) {
            hardDeleteInput.checked = false;
          }
        });
      });
    }
  }

  function slugify(value) {
    return String(value || '')
      .normalize('NFKD')
      .replace(/[^\w\s-]/g, '')
      .trim()
      .toLowerCase()
      .replace(/[\s_-]+/g, '-')
      .replace(/^-+|-+$/g, '');
  }

  async function uploadImage(url, file) {
    const formData = new FormData();
    formData.append('file', file);

    const res = await fetch(url, {
      method: 'POST',
      headers: {
        'X-CSRFToken': csrfToken,
      },
      body: formData,
    });

    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.success === false) {
      throw new Error(data.error || 'Upload failed');
    }

    return data;
  }

  function initBlogEditor() {
    const form = document.getElementById('blogEditorForm');
    if (!form) {
      return;
    }

    const initialData = window.__BLOG_EDITOR_DATA__ || {};
    const saveUrl = form.dataset.saveUrl;
    const coverUploadUrl = form.dataset.uploadCoverUrl;
    const inlineUploadUrl = form.dataset.uploadInlineImageUrl;

    const titleInput = document.getElementById('titleInput');
    const slugInput = document.getElementById('slugInput');
    const slugPreviewUrl = document.getElementById('slugPreviewUrl');
    const submitActionInput = document.getElementById('submitActionInput');
    const contentInput = document.getElementById('blogContentInput');
    const summaryInput = document.getElementById('summaryInput');
    const summaryCount = document.getElementById('summaryCount');
    const readingTimeBadge = document.getElementById('readingTimeBadge');
    const autoSaveStatus = document.getElementById('autoSaveStatus');
    const postIdInput = document.getElementById('postIdInput');
  const statusSelect = document.getElementById('statusSelect');

    const seoTitleInput = document.getElementById('metaTitleInput');
    const seoDescriptionInput = document.getElementById('metaDescriptionInput');
    const seoPreviewTitle = document.getElementById('seoPreviewTitle');
    const seoPreviewUrl = document.getElementById('seoPreviewUrl');
    const seoPreviewDescription = document.getElementById('seoPreviewDescription');

    const coverDropZone = document.getElementById('coverDropZone');
    const coverBrowseButton = document.getElementById('coverBrowseButton');
    const coverFileInput = document.getElementById('coverFileInput');
    const coverPreviewImage = document.getElementById('coverPreviewImage');
    const coverImageUrlInput = document.getElementById('coverImageUrlInput');
    const coverUploadStatus = document.getElementById('coverUploadStatus');

    let isSlugDirty = Boolean(initialData.slug);
    let lastAutosavePayload = '';
    let isSaving = false;

    const quill = new Quill('#blogEditor', {
      theme: 'snow',
      modules: {
        toolbar: {
          container: '#editorToolbar',
          handlers: {
            image: async () => {
              if (!inlineUploadUrl) {
                return;
              }
              const fileInput = document.createElement('input');
              fileInput.type = 'file';
              fileInput.accept = 'image/jpeg,image/png,image/webp';
              fileInput.click();

              fileInput.addEventListener('change', async () => {
                const file = fileInput.files?.[0];
                if (!file) {
                  return;
                }
                try {
                  const upload = await uploadImage(inlineUploadUrl, file);
                  const range = quill.getSelection(true);
                  quill.insertEmbed(range.index, 'image', upload.url, 'user');
                } catch (error) {
                  showToast(error.message || 'Image upload failed.', 'danger');
                }
              });
            },
          },
        },
      },
    });

    if (initialData.content) {
      quill.clipboard.dangerouslyPasteHTML(initialData.content);
    }

    function syncSummaryCount() {
      const text = String(summaryInput?.value || '');
      if (summaryCount) {
        summaryCount.textContent = text.length;
      }
    }

    function syncSlugPreview() {
      const slug = slugInput?.value?.trim() || 'post-slug';
      if (slugPreviewUrl) {
        slugPreviewUrl.textContent = `/blog/${slug}`;
      }
      if (seoPreviewUrl) {
        seoPreviewUrl.textContent = `https://quorum.org/blog/${slug}`;
      }
    }

    function syncSeoPreview() {
      const title = seoTitleInput?.value?.trim() || titleInput?.value?.trim() || 'Post title...';
      const description = seoDescriptionInput?.value?.trim() || summaryInput?.value?.trim() || 'Meta description preview appears here.';
      if (seoPreviewTitle) {
        seoPreviewTitle.textContent = title;
      }
      if (seoPreviewDescription) {
        seoPreviewDescription.textContent = description;
      }
      syncSlugPreview();
    }

    function updateReadingTime() {
      const text = quill.getText().trim();
      const words = text ? text.split(/\s+/).filter(Boolean).length : 0;
      const minutes = Math.max(1, Math.ceil(words / 200));
      if (readingTimeBadge) {
        readingTimeBadge.textContent = `${minutes} min read`;
      }
    }

    function syncContentInput() {
      if (!contentInput) {
        return;
      }
      contentInput.value = quill.root.innerHTML;
      updateReadingTime();
    }

    function setAutosaveStatus(message, isError = false) {
      if (!autoSaveStatus) {
        return;
      }
      autoSaveStatus.textContent = message;
      autoSaveStatus.classList.toggle('text-danger', isError);
      autoSaveStatus.classList.toggle('text-muted', !isError);
    }

    async function autosaveDraft() {
      if (isSaving) {
        return;
      }

      syncContentInput();
      const payload = {
        post_id: postIdInput?.value || '',
        title: titleInput?.value || '',
        slug: slugInput?.value || '',
        content: contentInput?.value || '',
        category: document.getElementById('categorySelect')?.value || '',
        tags: document.getElementById('tagsInput')?.value || '',
        summary: summaryInput?.value || '',
        cover_image_url: coverImageUrlInput?.value || '',
        cover_image_alt: document.getElementById('coverAltInput')?.value || '',
        meta_title: seoTitleInput?.value || '',
        meta_description: seoDescriptionInput?.value || '',
        status: statusSelect?.value || 'draft',
        is_featured: document.getElementById('featuredToggle')?.checked,
        is_pinned: document.getElementById('pinnedToggle')?.checked,
        published_at: document.getElementById('publishedAtInput')?.value || '',
        autosave: true,
        submit_action: 'save_draft',
      };

      const serialized = JSON.stringify(payload);
      if (serialized === lastAutosavePayload) {
        return;
      }

      if (!payload.title.trim() && !payload.content.replace(/<[^>]+>/g, '').trim()) {
        return;
      }

      isSaving = true;
      setAutosaveStatus('Saving...');
      try {
        const data = await postJson(saveUrl, payload);
        lastAutosavePayload = serialized;
        setAutosaveStatus('Saved');
        if (postIdInput && !postIdInput.value && data.post_id) {
          postIdInput.value = String(data.post_id);
        }
      } catch (error) {
        setAutosaveStatus(error.message || 'Autosave failed', true);
      } finally {
        isSaving = false;
      }
    }

    async function handleCoverUpload(file) {
      if (!file) {
        return;
      }
      if (coverUploadStatus) {
        coverUploadStatus.textContent = 'Uploading cover image...';
      }
      try {
        const data = await uploadImage(coverUploadUrl, file);
        if (coverImageUrlInput) {
          coverImageUrlInput.value = data.storage_path || '';
        }
        if (coverPreviewImage) {
          coverPreviewImage.src = data.url || '';
          coverPreviewImage.classList.remove('d-none');
        }
        if (coverUploadStatus) {
          coverUploadStatus.textContent = 'Cover image uploaded.';
        }
      } catch (error) {
        if (coverUploadStatus) {
          coverUploadStatus.textContent = error.message || 'Upload failed.';
        }
        showToast(error.message || 'Upload failed.', 'danger');
      }
    }

    titleInput?.addEventListener('input', () => {
      if (!isSlugDirty && slugInput) {
        slugInput.value = slugify(titleInput.value);
      }
      syncSeoPreview();
      syncSlugPreview();
    });

    slugInput?.addEventListener('input', () => {
      isSlugDirty = true;
      syncSlugPreview();
      syncSeoPreview();
    });

    summaryInput?.addEventListener('input', () => {
      syncSummaryCount();
      syncSeoPreview();
    });

    seoTitleInput?.addEventListener('input', syncSeoPreview);
    seoDescriptionInput?.addEventListener('input', syncSeoPreview);

    quill.on('text-change', () => {
      syncContentInput();
    });

    document.querySelectorAll('.js-submit-action').forEach((button) => {
      button.addEventListener('click', () => {
        if (submitActionInput) {
          submitActionInput.value = button.dataset.submitAction || 'save_draft';
        }
        if (button.dataset.submitAction === 'publish_now' && statusSelect) {
          statusSelect.value = 'published';
        }
        if (button.dataset.submitAction === 'save_draft' && statusSelect && statusSelect.value === 'published') {
          statusSelect.value = 'draft';
        }
        syncContentInput();
        form.submit();
      });
    });

    form.addEventListener('submit', () => {
      syncContentInput();
    });

    document.querySelector('.ql-divider')?.addEventListener('click', () => {
      const range = quill.getSelection(true);
      quill.clipboard.dangerouslyPasteHTML(range.index, '<hr>');
    });

    document.querySelector('.ql-table')?.addEventListener('click', () => {
      const range = quill.getSelection(true);
      const tableMarkup = '<table><thead><tr><th>Header</th><th>Header</th></tr></thead><tbody><tr><td>Cell</td><td>Cell</td></tr></tbody></table><p><br></p>';
      quill.clipboard.dangerouslyPasteHTML(range.index, tableMarkup);
    });

    coverBrowseButton?.addEventListener('click', () => {
      coverFileInput?.click();
    });

    coverFileInput?.addEventListener('change', () => {
      const file = coverFileInput.files?.[0];
      handleCoverUpload(file);
    });

    coverDropZone?.addEventListener('dragover', (event) => {
      event.preventDefault();
      coverDropZone.classList.add('is-dragover');
    });

    coverDropZone?.addEventListener('dragleave', () => {
      coverDropZone.classList.remove('is-dragover');
    });

    coverDropZone?.addEventListener('drop', (event) => {
      event.preventDefault();
      coverDropZone.classList.remove('is-dragover');
      const file = event.dataTransfer?.files?.[0];
      handleCoverUpload(file);
    });

    syncContentInput();
    syncSummaryCount();
    syncSeoPreview();
    syncSlugPreview();
    updateReadingTime();

    window.setInterval(() => {
      autosaveDraft();
    }, 60000);
  }

  document.addEventListener('DOMContentLoaded', () => {
    initBlogListingActions();
    initBlogEditor();
  });
})();
