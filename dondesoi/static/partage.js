/* Partage du lien d'invitation : menu de partage du téléphone quand il existe,
 * sinon copie dans le presse-papiers. */
(function () {
  "use strict";

  function copier(texte, ok) {
    var done = function () { if (ok) { ok.hidden = false; setTimeout(function () { ok.hidden = true; }, 2500); } };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(texte).then(done);
    } else {
      var champ = document.createElement("textarea");
      champ.value = texte;
      document.body.appendChild(champ);
      champ.select();
      document.execCommand("copy");
      champ.remove();
      done();
    }
  }

  var ok = document.querySelector("[data-copie-ok]");
  document.querySelectorAll("[data-copier]").forEach(function (b) {
    b.addEventListener("click", function () {
      copier(document.querySelector(b.dataset.copier).value, ok);
    });
  });
  document.querySelectorAll("[data-partager]").forEach(function (b) {
    b.addEventListener("click", function () {
      var data = { title: "Don de soi", text: b.dataset.texte, url: b.dataset.url };
      if (navigator.share) {
        navigator.share(data).catch(function () {});   // annulé par l'utilisateur : rien à faire
      } else {
        copier(b.dataset.texte + " " + b.dataset.url, ok);
      }
    });
  });
})();
