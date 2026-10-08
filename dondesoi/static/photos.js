/* Prise de photos depuis le téléphone pour les annonces.
 *
 * Sans JavaScript, le formulaire reste utilisable : le champ « galerie »
 * envoie directement ses fichiers. Avec JavaScript :
 *  - « Prendre une photo » ouvre l'appareil photo, et l'on peut enchaîner
 *    plusieurs prises de vue ;
 *  - chaque image est réduite dans le téléphone avant l'envoi (envoi rapide,
 *    et les métadonnées comme la position GPS ne quittent pas l'appareil) ;
 *  - un aperçu permet de retirer une photo avant de publier.
 * Le serveur réencode de toute façon chaque image (photos.py).
 */
(function () {
  "use strict";

  var MAX_SIZE = 1600;
  var QUALITY = 0.85;

  function resize(file) {
    if (!window.createImageBitmap || !file.type.startsWith("image/")) {
      return Promise.resolve(file);
    }
    return createImageBitmap(file, { imageOrientation: "from-image" })
      .then(function (bitmap) {
        var scale = Math.min(1, MAX_SIZE / Math.max(bitmap.width, bitmap.height));
        var canvas = document.createElement("canvas");
        canvas.width = Math.round(bitmap.width * scale);
        canvas.height = Math.round(bitmap.height * scale);
        var ctx = canvas.getContext("2d");
        ctx.fillStyle = "#fff";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
        bitmap.close && bitmap.close();
        return new Promise(function (resolve) {
          canvas.toBlob(function (blob) {
            if (!blob) { resolve(file); return; }
            var name = file.name.replace(/\.[^.]*$/, "") + ".jpg";
            resolve(new File([blob], name, { type: "image/jpeg" }));
          }, "image/jpeg", QUALITY);
        });
      })
      .catch(function () { return file; });   // format inconnu : le serveur tranchera
  }

  function setup(zone) {
    var target = zone.querySelector("[data-photos-target]");
    var inputs = zone.querySelectorAll("[data-photos-source]");
    var preview = zone.querySelector("[data-photos-preview]");
    var counter = zone.querySelector("[data-photos-count]");
    var max = parseInt(zone.dataset.max || "6", 10);
    var files = [];

    // DataTransfer permet de remplir un champ fichier par script ; sinon on
    // garde le fonctionnement sans JavaScript.
    try { new DataTransfer(); } catch (e) { return; }

    inputs.forEach(function (input) { input.removeAttribute("name"); });
    target.setAttribute("name", target.dataset.name);
    zone.classList.add("photos-js");

    function sync() {
      var dt = new DataTransfer();
      files.forEach(function (f) { dt.items.add(f); });
      target.files = dt.files;
      render();
    }

    function render() {
      preview.innerHTML = "";
      files.forEach(function (file, i) {
        var item = document.createElement("div");
        item.className = "photo-preview";
        var img = document.createElement("img");
        img.alt = "Photo " + (i + 1);
        img.src = URL.createObjectURL(file);
        img.onload = function () { URL.revokeObjectURL(img.src); };
        var remove = document.createElement("button");
        remove.type = "button";
        remove.className = "photo-remove";
        remove.setAttribute("aria-label", "Retirer la photo " + (i + 1));
        remove.textContent = "×";
        remove.onclick = function () { files.splice(i, 1); sync(); };
        item.appendChild(img);
        item.appendChild(remove);
        preview.appendChild(item);
      });
      var left = max - files.length;
      if (counter) {
        counter.textContent = files.length
          ? files.length + " photo" + (files.length > 1 ? "s" : "") + " · encore " + left + " possible" + (left > 1 ? "s" : "")
          : "";
      }
      inputs.forEach(function (input) {
        input.disabled = left <= 0;
        input.closest("label").classList.toggle("is-disabled", left <= 0);
      });
    }

    inputs.forEach(function (input) {
      input.addEventListener("change", function () {
        var picked = Array.prototype.slice.call(input.files, 0, Math.max(0, max - files.length));
        input.value = "";   // permet de reprendre une photo identique
        zone.classList.add("is-busy");
        Promise.all(picked.map(resize)).then(function (resized) {
          files = files.concat(resized);
          zone.classList.remove("is-busy");
          sync();
        });
      });
    });
    render();
  }

  document.querySelectorAll("[data-photos]").forEach(setup);
})();
