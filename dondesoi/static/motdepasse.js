/* Bouton « Afficher / Masquer » sur chaque champ de mot de passe, pour vérifier ce
 * que l'on tape. Le mot de passe enregistré, lui, ne peut jamais être affiché :
 * le site n'en garde qu'une empreinte chiffrée. */
(function () {
  "use strict";
  document.querySelectorAll('input[type="password"]').forEach(function (input) {
    var wrap = document.createElement("div");
    wrap.className = "password-wrap";
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);

    var button = document.createElement("button");
    button.type = "button";
    button.className = "password-toggle";
    button.setAttribute("aria-controls", input.id || "");
    var update = function () {
      var visible = input.type === "text";
      button.textContent = visible ? "Masquer" : "Afficher";
      button.setAttribute("aria-label", visible ? "Masquer le mot de passe" : "Afficher le mot de passe");
      button.setAttribute("aria-pressed", visible ? "true" : "false");
    };
    button.addEventListener("click", function () {
      input.type = input.type === "password" ? "text" : "password";
      update();
      input.focus();
    });
    // Par prudence, le mot de passe est de nouveau masqué au moment d'envoyer le formulaire.
    if (input.form) {
      input.form.addEventListener("submit", function () { input.type = "password"; update(); });
    }
    update();
    wrap.appendChild(button);
  });
})();
