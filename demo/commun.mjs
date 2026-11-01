// Outils communs aux scripts d'enregistrement des démos :
// lancement du navigateur, curseur visible et gestes « humains ».

import { chromium } from "playwright";

export const LARGEUR = 1280;
export const HAUTEUR = 720;

export const pause = (ms) => new Promise((r) => setTimeout(r, ms));

export const dansNJours = (n) => new Date(Date.now() + n * 86_400_000).toISOString().slice(0, 10);

// ---------- Navigateur ----------

export async function lancerNavigateur() {
  const env = { ...process.env, LANG: "fr_FR.UTF-8", LANGUAGE: "fr" };

  // channel "chromium" : vrai Chromium en mode sans fenêtre
  // LANG/LANGUAGE : langue de l'interface de Chromium sous Linux (format des champs date)
  return chromium.launch({ headless: true, channel: "chromium", args: ["--lang=fr-FR"], env });
}

// fenetre : taille de la page dans le navigateur. La vidéo, elle, fait toujours 1280×720
// (Playwright réduit l'image si la fenêtre est plus grande).
export function reglagesContexte(sortieVideo, fenetre = { width: LARGEUR, height: HAUTEUR }) {
  const reglages = { viewport: fenetre, locale: "fr-FR" };
  if (sortieVideo) {
    reglages.recordVideo = { dir: sortieVideo, size: { width: LARGEUR, height: HAUTEUR } };
  }
  return reglages;
}

// ---------- Curseur visible (Playwright ne filme pas la souris) ----------

export async function afficherCurseur(contexte, { couleur = "#c9a227", taille = 20 } = {}) {
  await contexte.addInitScript(({ couleur, taille }) => {
    window.addEventListener("DOMContentLoaded", () => {
      const curseur = document.createElement("div");
      curseur.style.cssText =
        `position:fixed;z-index:2147483647;width:${taille}px;height:${taille}px;border-radius:50%;` +
        `background:${couleur}55;border:2px solid ${couleur};pointer-events:none;` +
        "transform:translate(-50%,-50%);transition:transform .1s;";
      const [x, y] = JSON.parse(sessionStorage.getItem("curseur") ?? "[-50,-50]");
      curseur.style.left = `${x}px`;
      curseur.style.top = `${y}px`;
      document.body.appendChild(curseur);

      document.addEventListener(
        "mousemove",
        (e) => {
          curseur.style.left = `${e.clientX}px`;
          curseur.style.top = `${e.clientY}px`;
          sessionStorage.setItem("curseur", JSON.stringify([e.clientX, e.clientY]));
        },
        true,
      );
      document.addEventListener("mousedown", () => (curseur.style.transform = "translate(-50%,-50%) scale(.6)"), true);
      document.addEventListener("mouseup", () => (curseur.style.transform = "translate(-50%,-50%) scale(1)"), true);
    });
  }, { couleur, taille });
}

// ---------- Gestes ----------
// gestes(page) renvoie des actions qui bougent la souris progressivement avant d'agir,
// pour que la vidéo ressemble à une vraie utilisation.

export function gestes(page, { frappe = 30 } = {}) {
  const { width, height } = page.viewportSize();
  let souris = { x: width / 2, y: height / 2 };

  async function deplacerVers(selecteur) {
    const cible = typeof selecteur === "string" ? page.locator(selecteur).first() : selecteur;
    await cible.scrollIntoViewIfNeeded();
    const boite = await cible.boundingBox();
    const arrivee = { x: boite.x + boite.width / 2, y: boite.y + boite.height / 2 };
    const etapes = 10;
    for (let i = 1; i <= etapes; i++) {
      const t = i / etapes;
      const adouci = t * t * (3 - 2 * t);
      await page.mouse.move(souris.x + (arrivee.x - souris.x) * adouci, souris.y + (arrivee.y - souris.y) * adouci);
      await pause(5);
    }
    souris = arrivee;
    return cible;
  }

  async function cliquer(selecteur) {
    const cible = await deplacerVers(selecteur);
    await pause(100);
    await cible.click();
  }

  async function ecrire(selecteur, texte) {
    await cliquer(selecteur);
    await page.locator(selecteur).first().pressSequentially(texte, { delay: frappe });
  }

  // Clic qui charge une nouvelle page (lien, formulaire) : on attend la fin du chargement.
  async function cliquerEtAttendre(selecteur) {
    await Promise.all([page.waitForNavigation({ waitUntil: "load" }), cliquer(selecteur)]);
    await page.evaluate(() => document.fonts.ready);
  }

  // Défilement progressif (molette), pour montrer le bas d'une page.
  async function defiler(pixels, duree = 800) {
    const pas = 20;
    for (let i = 0; i < pas; i++) {
      await page.mouse.wheel(0, pixels / pas);
      await pause(duree / pas);
    }
  }

  // Défilement en douceur jusqu'à un élément (scrollIntoView ferait un saut brusque à l'écran).
  async function defilerVers(selecteur, decalage = 200) {
    await page.locator(selecteur).first().evaluate((el, decalage) => {
      window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - decalage, behavior: "smooth" });
    }, decalage);
    await pause(900);
  }

  return { deplacerVers, cliquer, ecrire, cliquerEtAttendre, defiler, defilerVers };
}

// En cas d'échec : capture et adresse de la page, pour comprendre ce qui a bloqué.
export async function signalerEchec(page, fichierCapture) {
  await page.screenshot({ path: fichierCapture }).catch(() => {});
  console.error(`Échec sur ${page.url()} (capture : ${fichierCapture})`);
}

// Chronomètre : affiche le temps écoulé à chaque étape, pour régler la durée des vidéos.
export function chrono() {
  const debut = Date.now();
  return (etape) => console.log(`  ${((Date.now() - debut) / 1000).toFixed(1).padStart(5)} s  ${etape}`);
}
