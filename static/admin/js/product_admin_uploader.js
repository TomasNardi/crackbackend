/**
 * product_admin.js
 * - Fieldsets condicionales por categoría.
 * - Uploader marketplace (drag & drop, file picker, URL, progress, preview, remove, replace, reorder).
 */
(function () {
  'use strict';

  const SINGLES_SLUGS = ['singles'];
  const SLABS_SLUGS = ['slabs'];
  const MAX_IMAGES = 3;
  const MAX_SIZE_BYTES = 10 * 1024 * 1024;
  const ALLOWED_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp', 'avif'];

  const API = {
    signature: '/api/v1/products/admin/cloudinary/signature/',
    register: '/api/v1/products/admin/cloudinary/register-upload/',
    del: '/api/v1/products/admin/cloudinary/delete/'
  };

  let state = { images: [] };
  let dragSourceIndex = null;

  function getSelectedCategoryText() {
    const select = document.getElementById('id_category');
    if (!select) return '';
    const opt = select.options[select.selectedIndex];
    if (!opt || !opt.value) return '';
    return opt.text.trim().toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '');
  }

  function findFieldset(cssClass) {
    return document.querySelector('fieldset.' + cssClass);
  }

  function applyFieldset(fieldset, enabled) {
    if (!fieldset) return;
    fieldset.style.display = enabled ? '' : 'none';
    const controls = fieldset.querySelectorAll('select, input[type="text"], input[type="number"], input[type="hidden"], textarea');
    controls.forEach((el) => {
      if (!enabled) {
        el.value = '';
        el.disabled = true;
      } else {
        el.disabled = false;
      }
    });
  }

  function updateFieldsets() {
    const slug = getSelectedCategoryText();
    const singlesFS = findFieldset('fieldset-singles');
    const slabsFS = findFieldset('fieldset-slabs');
    const isSingle = slug && SINGLES_SLUGS.some((s) => slug.includes(s));
    const isSlab = slug && SLABS_SLUGS.some((s) => slug.includes(s));
    applyFieldset(singlesFS, isSingle);
    applyFieldset(slabsFS, isSlab);
  }

  function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
    return '';
  }

  function csrfHeaders() {
    return {
      'Content-Type': 'application/json',
      'X-CSRFToken': getCookie('csrftoken')
    };
  }

  function getField(id) {
    return document.getElementById(id);
  }

  function getDraftToken() {
    const input = getField('id_cloudinary_draft_token');
    return input ? input.value : '';
  }

  function setLegacyUrlFields() {
    const urls = state.images.map((img) => img.secure_url || '').slice(0, 3);
    while (urls.length < 3) urls.push('');
    const id1 = getField('id_image_url');
    const id2 = getField('id_image_url_2');
    const id3 = getField('id_image_url_3');
    if (id1) id1.value = urls[0];
    if (id2) id2.value = urls[1];
    if (id3) id3.value = urls[2];
  }

  function syncPayloadField() {
    const field = getField('id_images_payload');
    if (!field) return;
    const payload = state.images.map((img, index) => ({
      id: img.id || null,
      order_index: index,
      secure_url: img.secure_url,
      public_id: img.public_id || '',
      source: img.source || 'cloudinary',
      status: img.status || 'uploaded'
    }));
    field.value = JSON.stringify(payload);
    setLegacyUrlFields();
  }

  function showToast(message, tone) {
    const root = document.querySelector('.product-uploader-root');
    if (!root) return;
    const toast = document.createElement('div');
    toast.className = `product-uploader-toast ${tone || 'info'}`;
    toast.textContent = message;
    root.appendChild(toast);
    setTimeout(() => toast.remove(), 2800);
  }

  function validateFile(file) {
    const ext = (file.name.split('.').pop() || '').toLowerCase();
    if (!ALLOWED_EXTENSIONS.includes(ext)) {
      throw new Error('Formato inválido. Usa JPG, PNG, WEBP o AVIF.');
    }
    if (file.size > MAX_SIZE_BYTES) {
      throw new Error('Archivo demasiado grande (máximo 10MB).');
    }
  }

  async function requestSignature(slot) {
    const draftToken = getDraftToken();
    const response = await fetch(API.signature, {
      method: 'POST',
      headers: csrfHeaders(),
      credentials: 'same-origin',
      body: JSON.stringify({ draft_token: draftToken, slot })
    });
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || 'No se pudo generar firma de upload.');
    }
    return response.json();
  }

  async function registerUpload(image, orderIndex) {
    const payload = {
      draft_token: getDraftToken(),
      secure_url: image.secure_url,
      public_id: image.public_id || '',
      source: image.source || 'cloudinary',
      order_index: orderIndex,
      metadata: image.metadata || {}
    };

    const response = await fetch(API.register, {
      method: 'POST',
      headers: csrfHeaders(),
      credentials: 'same-origin',
      body: JSON.stringify(payload)
    });
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || 'No se pudo registrar la imagen.');
    }
    return response.json();
  }

  async function uploadToCloudinary(file, slot, onProgress) {
    const signed = await requestSignature(slot);
    return new Promise((resolve, reject) => {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('api_key', signed.api_key);
      fd.append('timestamp', signed.timestamp);
      fd.append('upload_preset', signed.upload_preset);
      fd.append('context', signed.context);
      fd.append('notification_url', signed.notification_url);
      fd.append('signature', signed.signature);

      const xhr = new XMLHttpRequest();
      xhr.open('POST', signed.upload_url, true);
      xhr.upload.onprogress = function (evt) {
        if (!evt.lengthComputable) return;
        onProgress(Math.round((evt.loaded / evt.total) * 100));
      };
      xhr.onload = function () {
        if (xhr.status < 200 || xhr.status >= 300) {
          reject(new Error('Upload fallido en Cloudinary.'));
          return;
        }
        const data = JSON.parse(xhr.responseText || '{}');
        resolve(data);
      };
      xhr.onerror = function () {
        reject(new Error('Error de red subiendo imagen.'));
      };
      xhr.send(fd);
    });
  }

  function setUploadingCardAt(index, file) {
    const card = {
      id: null,
      secure_url: URL.createObjectURL(file),
      public_id: '',
      source: 'cloudinary',
      status: 'pending',
      progress: 0,
      _localPreview: true
    };
    if (index >= state.images.length) {
      state.images.push(card);
    } else {
      const replaced = state.images[index];
      if (replaced && replaced._localPreview) {
        URL.revokeObjectURL(replaced.secure_url);
      }
      state.images[index] = card;
    }
    return card;
  }

  async function uploadFile(file, replaceIndex) {
    validateFile(file);

    if (replaceIndex == null && state.images.length >= MAX_IMAGES) {
      throw new Error('Máximo 3 imágenes por producto.');
    }

    const targetIndex = replaceIndex == null ? state.images.length : replaceIndex;
    const localCard = setUploadingCardAt(targetIndex, file);
    renderGallery();

    const cloudinaryData = await uploadToCloudinary(file, targetIndex, function (progress) {
      localCard.progress = progress;
      renderGallery();
    });

    const registered = await registerUpload({
      secure_url: cloudinaryData.secure_url,
      public_id: cloudinaryData.public_id,
      source: 'cloudinary',
      metadata: {
        width: cloudinaryData.width,
        height: cloudinaryData.height,
        bytes: cloudinaryData.bytes,
        format: cloudinaryData.format
      }
    }, targetIndex);

    if (localCard._localPreview) {
      URL.revokeObjectURL(localCard.secure_url);
    }

    state.images[targetIndex] = {
      id: registered.id,
      secure_url: registered.secure_url,
      public_id: registered.public_id,
      source: registered.source,
      status: registered.status,
      progress: 100
    };
    syncPayloadField();
    renderGallery();
  }

  async function addImageByUrl(url) {
    if (!url || !/^https?:\/\//i.test(url)) {
      throw new Error('La URL debe iniciar con http:// o https://');
    }
    if (state.images.length >= MAX_IMAGES) {
      throw new Error('Máximo 3 imágenes por producto.');
    }

    const orderIndex = state.images.length;
    const registered = await registerUpload({
      secure_url: url,
      public_id: '',
      source: 'url',
      metadata: { manual_url: true }
    }, orderIndex);

    state.images.push({
      id: registered.id,
      secure_url: registered.secure_url,
      public_id: registered.public_id,
      source: registered.source,
      status: registered.status,
      progress: 100
    });
    syncPayloadField();
    renderGallery();
  }

  async function removeImage(index) {
    const image = state.images[index];
    if (!image) return;

    if (image.id) {
      const response = await fetch(API.del, {
        method: 'POST',
        headers: csrfHeaders(),
        credentials: 'same-origin',
        body: JSON.stringify({ image_id: image.id })
      });
      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.detail || 'No se pudo eliminar la imagen.');
      }
    }

    if (image._localPreview) {
      URL.revokeObjectURL(image.secure_url);
    }
    state.images.splice(index, 1);
    syncPayloadField();
    renderGallery();
  }

  function moveImage(fromIndex, toIndex) {
    if (fromIndex === toIndex) return;
    const item = state.images.splice(fromIndex, 1)[0];
    state.images.splice(toIndex, 0, item);
    syncPayloadField();
    renderGallery();
  }

  function renderGallery() {
    const grid = document.querySelector('.product-uploader-grid');
    const counter = document.querySelector('.product-uploader-counter');
    if (!grid) return;

    grid.innerHTML = '';
    state.images.forEach((img, index) => {
      const card = document.createElement('article');
      card.className = 'product-image-card';
      card.draggable = true;
      card.dataset.index = String(index);
      card.innerHTML = `
        <div class="product-image-preview-wrap">
          <img class="product-image-preview" src="${img.secure_url}" alt="Imagen ${index + 1}" />
          ${img.progress < 100 ? `<div class="upload-progress"><span style="width:${img.progress || 0}%"></span></div>` : ''}
        </div>
        <div class="product-image-meta">
          <strong>#${index + 1}</strong>
          <small>${img.source === 'url' ? 'URL' : 'Cloudinary'}</small>
        </div>
        <div class="product-image-actions">
          <button type="button" class="replace-image-btn" data-index="${index}">Reemplazar</button>
          <button type="button" class="remove-image-btn danger" data-index="${index}">Eliminar</button>
        </div>
      `;

      card.addEventListener('dragstart', function () {
        dragSourceIndex = index;
      });
      card.addEventListener('dragover', function (evt) {
        evt.preventDefault();
        card.classList.add('drag-over');
      });
      card.addEventListener('dragleave', function () {
        card.classList.remove('drag-over');
      });
      card.addEventListener('drop', function (evt) {
        evt.preventDefault();
        card.classList.remove('drag-over');
        if (dragSourceIndex == null) return;
        moveImage(dragSourceIndex, index);
        dragSourceIndex = null;
      });

      grid.appendChild(card);
    });

    if (counter) {
      counter.textContent = `${state.images.length}/${MAX_IMAGES}`;
    }
  }

  function parseInitialPayload() {
    const raw = (getField('id_images_payload') || {}).value || '[]';
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        return parsed
          .filter((item) => item && item.secure_url)
          .slice(0, MAX_IMAGES)
          .map((item) => ({
            id: item.id || null,
            secure_url: item.secure_url,
            public_id: item.public_id || '',
            source: item.source || 'url',
            status: item.status || 'confirmed',
            progress: 100
          }));
      }
      return [];
    } catch (err) {
      return [];
    }
  }

  function buildUploaderUI() {
    const legacyField = getField('id_image_url');
    if (!legacyField) return;

    const root = document.createElement('section');
    root.className = 'product-uploader-root';
    root.innerHTML = `
      <header class="product-uploader-header">
        <h3>Galería de imágenes</h3>
        <span class="product-uploader-counter">0/${MAX_IMAGES}</span>
      </header>
      <div class="product-uploader-dropzone" id="product-dropzone">
        <p>Arrastrá y soltá imágenes acá</p>
        <small>o usá el selector manual (JPG, PNG, WEBP, AVIF · máximo 10MB)</small>
      </div>
      <div class="product-uploader-toolbar">
        <button type="button" class="select-files-btn">Seleccionar archivos</button>
        <input type="file" id="product-files-input" accept=".jpg,.jpeg,.png,.webp,.avif" multiple hidden />
        <input type="url" id="product-url-input" placeholder="https://..." />
        <button type="button" class="add-url-btn">Agregar URL</button>
      </div>
      <div class="product-uploader-grid" aria-live="polite"></div>
      <input type="file" id="replace-file-input" accept=".jpg,.jpeg,.png,.webp,.avif" hidden />
    `;

    const imageFieldset = legacyField.closest('fieldset') || document.querySelector('fieldset.module');
    const row =
      legacyField.closest('.form-row') ||
      legacyField.closest('.form-group') ||
      legacyField.closest('.field-box') ||
      legacyField.closest('.field-image_url') ||
      legacyField.parentElement;

    if (row && row.parentElement) {
      row.parentElement.insertBefore(root, row);
    } else if (imageFieldset) {
      imageFieldset.prepend(root);
    } else {
      legacyField.parentElement.insertBefore(root, legacyField);
    }

    ['id_image_url', 'id_image_url_2', 'id_image_url_3'].forEach((id) => {
      const input = getField(id);
      if (!input) return;
      const wrapper =
        input.closest('.form-row') ||
        input.closest('.form-group') ||
        input.closest('.field-box') ||
        input.closest('.field-image_url') ||
        input.closest('.field-image_url_2') ||
        input.closest('.field-image_url_3') ||
        input.parentElement;
      if (wrapper) wrapper.style.display = 'none';
    });

    const dropzone = root.querySelector('#product-dropzone');
    const filesInput = root.querySelector('#product-files-input');
    const replaceInput = root.querySelector('#replace-file-input');
    const urlInput = root.querySelector('#product-url-input');

    root.querySelector('.select-files-btn').addEventListener('click', function () {
      filesInput.click();
    });

    filesInput.addEventListener('change', async function (evt) {
      const files = Array.from(evt.target.files || []);
      evt.target.value = '';
      for (const file of files) {
        try {
          await uploadFile(file);
        } catch (err) {
          showToast(err.message, 'error');
        }
      }
    });

    root.querySelector('.add-url-btn').addEventListener('click', async function () {
      const value = (urlInput.value || '').trim();
      if (!value) return;
      try {
        await addImageByUrl(value);
        urlInput.value = '';
      } catch (err) {
        showToast(err.message, 'error');
      }
    });

    dropzone.addEventListener('dragover', function (evt) {
      evt.preventDefault();
      dropzone.classList.add('active');
    });
    dropzone.addEventListener('dragleave', function () {
      dropzone.classList.remove('active');
    });
    dropzone.addEventListener('drop', async function (evt) {
      evt.preventDefault();
      dropzone.classList.remove('active');
      const files = Array.from(evt.dataTransfer.files || []);
      for (const file of files) {
        try {
          await uploadFile(file);
        } catch (err) {
          showToast(err.message, 'error');
        }
      }
    });

    root.addEventListener('click', async function (evt) {
      const removeBtn = evt.target.closest('.remove-image-btn');
      if (removeBtn) {
        const index = Number(removeBtn.dataset.index);
        try {
          await removeImage(index);
        } catch (err) {
          showToast(err.message, 'error');
        }
        return;
      }

      const replaceBtn = evt.target.closest('.replace-image-btn');
      if (replaceBtn) {
        replaceInput.dataset.targetIndex = replaceBtn.dataset.index;
        replaceInput.click();
      }
    });

    replaceInput.addEventListener('change', async function (evt) {
      const file = (evt.target.files || [])[0];
      const targetIndex = Number(replaceInput.dataset.targetIndex);
      evt.target.value = '';
      if (!file || Number.isNaN(targetIndex)) return;

      try {
        await removeImage(targetIndex);
        await uploadFile(file, targetIndex);
      } catch (err) {
        showToast(err.message, 'error');
      }
    });
  }

  function init() {
    updateFieldsets();
    const categorySelect = document.getElementById('id_category');
    if (categorySelect) {
      categorySelect.addEventListener('change', updateFieldsets);
    }

    try {
      buildUploaderUI();
      state.images = parseInitialPayload();
      syncPayloadField();
      renderGallery();
    } catch (err) {
      console.error('Error inicializando uploader de productos', err);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

