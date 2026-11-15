/* Lost & Found+ — progressive enhancement.
   Everything here is optional: the site works without JavaScript. */
(function () {
  'use strict';

  // ----- Mobile navigation -----
  var nav = document.getElementById('siteNav');
  var navToggle = document.getElementById('navToggle');
  if (nav && navToggle) {
    navToggle.addEventListener('click', function () {
      var open = nav.classList.toggle('open');
      navToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      navToggle.innerHTML = open
        ? '<svg class="icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>'
        : '<svg class="icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M3 6h18M3 12h18M3 18h18"/></svg>';
    });
    document.addEventListener('click', function (event) {
      if (!nav.contains(event.target)) {
        nav.classList.remove('open');
        navToggle.setAttribute('aria-expanded', 'false');
      }
    });
  }

  // ----- User dropdown -----
  var userMenu = document.getElementById('userMenu');
  var userButton = document.getElementById('userMenuButton');
  if (userMenu && userButton) {
    userButton.addEventListener('click', function (event) {
      event.stopPropagation();
      var open = userMenu.classList.toggle('open');
      userButton.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    document.addEventListener('click', function (event) {
      if (!userMenu.contains(event.target)) {
        userMenu.classList.remove('open');
        userButton.setAttribute('aria-expanded', 'false');
      }
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && userMenu.classList.contains('open')) {
        userMenu.classList.remove('open');
        userButton.setAttribute('aria-expanded', 'false');
        userButton.focus();
      }
    });
  }

  // ----- Flash messages -----
  var stack = document.getElementById('flashStack');
  if (stack) {
    stack.addEventListener('click', function (event) {
      var button = event.target.closest('[data-dismiss]');
      if (button) {
        var flash = button.closest('.flash');
        if (flash) flash.remove();
      }
    });
    window.setTimeout(function () {
      stack.querySelectorAll('.flash').forEach(function (flash) {
        flash.style.transition = 'opacity .35s, transform .35s';
        flash.style.opacity = '0';
        flash.style.transform = 'translateX(16px)';
        window.setTimeout(function () { flash.remove(); }, 400);
      });
    }, 6500);
  }

  // ----- Confirm destructive actions -----
  document.querySelectorAll('form[data-confirm]').forEach(function (form) {
    form.addEventListener('submit', function (event) {
      if (!window.confirm(form.getAttribute('data-confirm'))) {
        event.preventDefault();
      }
    });
  });

  // ----- Auto-submit sort select -----
  document.querySelectorAll('[data-autosubmit]').forEach(function (select) {
    select.addEventListener('change', function () {
      if (select.form) select.form.submit();
    });
  });

  // ----- Mobile filter panel -----
  var filterToggle = document.getElementById('filterToggle');
  var filterPanel = document.getElementById('filterPanel');
  if (filterToggle && filterPanel) {
    filterToggle.addEventListener('click', function () {
      filterPanel.classList.toggle('open');
    });
  }

  // ----- Image preview before upload -----
  var imageInput = document.getElementById('image');
  var uploadPreview = document.getElementById('uploadPreview');
  if (imageInput && uploadPreview) {
    imageInput.addEventListener('change', function () {
      var file = imageInput.files && imageInput.files[0];
      if (!file) return;
      if (!/^image\//.test(file.type)) {
        window.alert('Please choose an image file.');
        imageInput.value = '';
        return;
      }
      if (file.size > 5 * 1024 * 1024) {
        window.alert('That image is larger than 5 MB. Please choose a smaller one.');
        imageInput.value = '';
        return;
      }
      var url = URL.createObjectURL(file);
      uploadPreview.innerHTML = '';
      var img = document.createElement('img');
      img.src = url;
      img.alt = 'Selected photo preview';
      img.onload = function () { URL.revokeObjectURL(url); };
      uploadPreview.appendChild(img);
    });
  }

  // ----- Loading state for submit buttons -----
  document.querySelectorAll('form').forEach(function (form) {
    form.addEventListener('submit', function (event) {
      if (event.defaultPrevented) return;
      var button = form.querySelector('button[data-loading][type="submit"]');
      if (!button || button.disabled) return;
      button.dataset.original = button.innerHTML;
      button.innerHTML = button.getAttribute('data-loading');
      button.disabled = true;
      // Re-enable if the browser restores the page from bfcache.
      window.setTimeout(function () {
        if (document.body.contains(button)) {
          button.disabled = false;
          button.innerHTML = button.dataset.original || button.innerHTML;
        }
      }, 12000);
    });
  });

  // ----- Close mobile nav after following an in-page link -----
  document.querySelectorAll('.nav-links a').forEach(function (link) {
    link.addEventListener('click', function () {
      if (nav) nav.classList.remove('open');
    });
  });
})();
