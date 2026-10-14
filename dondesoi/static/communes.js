/* Code postal → ville : dès que les 5 chiffres sont tapés, propose les communes portant ce
 * code (liste déroulante du champ ville) et remplit la ville s'il n'y en a qu'une. Le serveur
 * vérifie de toute façon la paire code postal / ville. */
(function () {
  "use strict";
  var cache = {};

  function charger(cp) {
    if (!cache[cp]) {
      cache[cp] = fetch("/communes/" + cp)
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (data) {
          if (data.communes === null) delete cache[cp];   // service indisponible : on réessaiera
          return data;
        })
        .catch(function () { delete cache[cp]; return { communes: null }; });
    }
    return cache[cp];
  }

  function norm(s) {
    return (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  }

  document.querySelectorAll("[data-cp-ville]").forEach(function (zone, i) {
    var cp = zone.querySelector("[data-cp]");
    var ville = zone.querySelector("[data-ville]");
    var aide = zone.querySelector("[data-cp-aide]");
    var liste = document.createElement("datalist");
    liste.id = "communes-" + i;
    zone.appendChild(liste);
    ville.setAttribute("list", liste.id);
    var noms = null;

    function verifier() {
      if (!noms || !ville.value) { ville.setCustomValidity(""); return; }
      var ok = noms.some(function (n) { return norm(n) === norm(ville.value); });
      ville.setCustomValidity(ok ? "" : "Cette ville n'a pas ce code postal.");
    }

    function maj() {
      var v = cp.value.trim();
      noms = null;
      liste.innerHTML = "";
      if (aide) aide.textContent = "";
      if (!/^\d{5}$/.test(v)) { verifier(); return; }
      charger(v).then(function (data) {
        if (cp.value.trim() !== v || data.communes === null) return;   // saisie changée ou service absent
        if (!data.communes.length) {
          if (aide) aide.textContent = "Code postal inconnu.";
          return;
        }
        noms = data.communes.map(function (c) { return c.nom; });
        data.communes.forEach(function (c) {
          var o = document.createElement("option");
          o.value = c.nom;
          o.label = c.nom + (c.dep ? " (" + c.dep + ")" : "");
          liste.appendChild(o);
        });
        if (noms.length === 1) {
          ville.value = noms[0];
        } else if (aide) {
          aide.textContent = noms.length + " communes avec ce code : " + noms.join(", ") + ".";
        }
        verifier();
      });
    }

    cp.addEventListener("input", maj);
    ville.addEventListener("input", verifier);
    if (cp.value) maj();
  });
})();
