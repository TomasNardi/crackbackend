/**
 * product_admin.js
 * Muestra/oculta Y limpia los fieldsets condicionales según la categoría.
 *
 * Singles  → habilitar Condición  | limpiar + deshabilitar Certificación
 * Slabs    → habilitar Certific.  | limpiar + deshabilitar Condición
 * Resto    → limpiar + deshabilitar ambos
 */
(function () {
  'use strict';

  const SINGLES_SLUGS = ['singles'];
  const SLABS_SLUGS   = ['slabs'];

  function getSelectedCategoryText() {
    const select = document.getElementById('id_category');
    if (!select) return '';
    const opt = select.options[select.selectedIndex];
    if (!opt || !opt.value) return '';
    return opt.text.trim().toLowerCase()
      .replace(/\s+/g, '-')
      .replace(/[^a-z0-9-]/g, '');
  }

  function findFieldset(cssClass) {
    return document.querySelector('fieldset.' + cssClass);
  }

  /**
   * Muestra u oculta un fieldset.
   * Si se oculta (enabled=false): limpia y deshabilita todos sus inputs/selects
   * para que no se envíen datos incorrectos ni queden valores "fantasma".
   */
  function applyFieldset(fieldset, enabled) {
    if (!fieldset) return;

    fieldset.style.display = enabled ? '' : 'none';

    const controls = fieldset.querySelectorAll('select, input[type="text"], input[type="number"], input[type="hidden"], textarea');
    controls.forEach((el) => {
      if (!enabled) {
        // Limpiar el valor
        if (el.tagName === 'SELECT') {
          el.value = '';
        } else {
          el.value = '';
        }
        el.disabled = true;
      } else {
        el.disabled = false;
      }
    });
  }

  function updateFieldsets() {
    const slug = getSelectedCategoryText();

    const singlesFS = findFieldset('fieldset-singles');
    const slabsFS   = findFieldset('fieldset-slabs');

    const isSingle = slug && SINGLES_SLUGS.some((s) => slug.includes(s));
    const isSlab   = slug && SLABS_SLUGS.some((s) => slug.includes(s));

    applyFieldset(singlesFS, isSingle);
    applyFieldset(slabsFS,   isSlab);
  }

  function init() {
    updateFieldsets(); // estado al cargar la página

    const categorySelect = document.getElementById('id_category');
    if (categorySelect) {
      categorySelect.addEventListener('change', updateFieldsets);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

