/**
 * Build Tailwind statique (remplace cdn.tailwindcss.com, déconseillé en prod).
 *
 * Génération :
 *   npx tailwindcss@3 -i static/css/tailwind.source.css \
 *       -o static/css/tailwind.min.css --minify
 *
 * À relancer après ajout de nouvelles classes utilitaires dans les
 * templates / le JS / les vues Python qui émettent des classes.
 */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./static/js/**/*.js",
    // Vues qui renvoient des classes CSS dans leurs payloads (labels colorés)
    "./*/views*.py",
    "./*/services*.py",
  ],
  theme: {
    extend: {},
  },
  plugins: [],
};
