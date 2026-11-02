// Enregistre la démo de la détection de phishing (TriLama + PhishingDetect) dans le webmail SOGo.
//
// Déroulé : connexion (non filmée) -> partie 1 filmée : écriture et envoi d'un faux mail de
// phishing -> attente de la détection (non filmée) -> partie 2 filmée : le mail est resté dans
// la boîte de réception avec l'étiquette « Phishing suspect ».
//
// Confidentialité : un mail suspect n'est pas rangé, il reste dans la boîte de réception, au milieu
// des vrais mails. Toutes les lignes de la liste qui ne contiennent pas la référence de la démo sont
// donc masquées à l'écran, en continu, avant même le premier affichage.

import { readFileSync } from "node:fs";
import { rename } from "node:fs/promises";
import { lancerNavigateur, reglagesContexte, afficherCurseur, gestes, pause, chrono, signalerEchec } from "./commun.mjs";

const SORTIE = process.env.SORTIE ?? "./tmp";
const WEBMAIL = "https://webmail.univ-rouen.fr/SOGo/";
const REF = new Date().toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Paris" }).replace(":", "");
const SUJET = `Votre compte ENT va être suspendu (réf. ${REF})`;
// Le décodage de l'en-tête peut ajouter des espaces (« réf.  0117 ») : on cherche la référence avec \s+
const MOTIF_REF = new RegExp(`réf\\.\\s+${REF}`);
const CORPS = [
  "Bonjour,",
  "",
  "Suite à une activité inhabituelle détectée sur votre compte, celui-ci sera désactivé sous 24 heures.",
  "Pour conserver l'accès à vos mails et à vos cours, confirmez votre identifiant et votre mot de passe ici :",
  "http://univ-r0uen-login.xyz/ent",
  "",
  "Le service informatique",
];

// Identifiants lus dans le .env du projet (jamais affichés)
const env = Object.fromEntries(
  readFileSync(new URL("../.env", import.meta.url), "utf8")
    .split("\n")
    .filter((l) => /^[A-Z_]+=/.test(l))
    .map((l) => [l.slice(0, l.indexOf("=")), l.slice(l.indexOf("=") + 1).trim()]),
);
const ADRESSE = env.NOTIFY_TO;
const top = chrono();

// Masque toutes les lignes de la liste des messages sauf celles de la démo.
// Exécuté dans la page avant tout chargement, puis toutes les 30 ms : la liste SOGo est virtualisée
// et réutilise ses lignes en défilant, un masquage ponctuel ne suffirait pas.
async function masquerAutresMails(contexte) {
  await contexte.addInitScript((source) => {
    const motif = new RegExp(source);
    const LIGNES = "md-virtual-repeat-container md-list-item, md-virtual-repeat-container .sg-message-list-item";
    const masquer = () => {
      for (const el of document.querySelectorAll(LIGNES)) {
        // data-demo : seule la ligne de la démo est autorisée à s'afficher (voir la règle CSS)
        if (motif.test(el.textContent)) el.setAttribute("data-demo", "");
        else el.removeAttribute("data-demo");
      }
    };
    // CSS posé dès le départ : toute ligne est invisible tant qu'elle n'a pas été vérifiée
    const style = document.createElement("style");
    style.textContent = "md-virtual-repeat-container md-list-item:not([data-demo]), md-virtual-repeat-container .sg-message-list-item:not([data-demo]) { visibility: hidden !important; }";
    const demarrer = () => {
      document.head.appendChild(style);
      new MutationObserver(masquer).observe(document.body, { childList: true, subtree: true, characterData: true });
      setInterval(masquer, 30);
      masquer();
    };
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", demarrer);
    else demarrer();
  }, MOTIF_REF.source);
}

const navigateur = await lancerNavigateur();

// ---------- Connexion (non filmée) ----------
const connexion = await navigateur.newContext(reglagesContexte(null));
const pageConnexion = await connexion.newPage();
await pageConnexion.goto(WEBMAIL);
await pageConnexion.locator('input[type="text"], input[name="username"]').first().fill(env.IMAP_USER);
await pageConnexion.locator('input[type="password"]').first().fill(env.IMAP_PASSWORD);
await pageConnexion.keyboard.press("Enter");
await pageConnexion.waitForURL(/\/so\/[^/]+\//, { timeout: 30_000 });
const base = pageConnexion.url().match(/^(.*\/so\/[^/]+\/)/)[1];
const BOITE = `${base}Mail/view#!/Mail/0/INBOX`;
const session = await connexion.storageState();
await connexion.close();
top("connecté");

async function ouvrirBoite(page) {
  await page.goto(BOITE);
  await page.getByText("message(s)").first().waitFor({ timeout: 30_000 });
  await page.evaluate(() => document.fonts.ready);
  await pause(800);
}

const lignes = (page) => page.locator("md-list-item, .sg-message-list-item, [role='listitem']").filter({ hasText: MOTIF_REF });

// ---------- Partie 1 : envoi du faux mail de phishing ----------
const contexte1 = await navigateur.newContext({ ...reglagesContexte(SORTIE), storageState: session });
await masquerAutresMails(contexte1);
await afficherCurseur(contexte1);
const page1 = await contexte1.newPage();
const g1 = gestes(page1, { frappe: 25 });
try {
  await ouvrirBoite(page1);
  await pause(1200);

  // Même méthode que la démo de TriLama (voir enregistrer-demo.mjs)
  const vert = page1.getByRole("button", { name: "Écrire un nouveau message" }).first();
  await g1.deplacerVers(vert);
  await pause(700);
  const dansLaPage = page1.getByRole("button", { name: "Écrire un nouveau message", exact: true }).nth(1);
  const boite = await dansLaPage.boundingBox().catch(() => null);
  if (boite) await page1.mouse.move(boite.x + boite.width / 2, boite.y + boite.height / 2, { steps: 8 });
  await pause(300);
  await page1.evaluate(() => {
    const boutons = [...document.querySelectorAll('button[aria-label="Écrire un nouveau message"]')];
    (boutons[1] ?? boutons[0]).click();
  });

  const dialogue = page1.locator("md-dialog").first();
  await dialogue.waitFor({ timeout: 15_000 });
  await pause(800);
  const champDest = dialogue.locator('input[name^="input-"]').filter({ visible: true }).first();
  const champSujet = dialogue.locator('input[name="subject"]');
  const champCorps = dialogue.locator(".ck-editor__editable").first();
  const boutonEnvoyer = dialogue.locator('button[ng-click="editor.send()"]');

  // Destinataire
  await g1.cliquer(champDest);
  await page1.keyboard.type(ADRESSE, { delay: 25 });
  await pause(1200);
  const puce = dialogue.locator("md-chip").filter({ hasText: /graine/i }).first();
  const suggestion = page1.locator("md-virtual-repeat-container:visible li, .md-autocomplete-suggestions li")
    .filter({ hasText: ADRESSE }).first();
  if (await suggestion.isVisible().catch(() => false)) await g1.cliquer(suggestion);
  else await page1.keyboard.press("Enter");
  if (!(await puce.isVisible({ timeout: 2500 }).catch(() => false))) {
    await page1.keyboard.press("Enter");
    if (!(await puce.isVisible().catch(() => false))) await page1.keyboard.press("Tab");
  }
  await puce.waitFor({ timeout: 8000 });
  await pause(400);

  // Sujet
  await g1.cliquer(champSujet);
  await page1.keyboard.type(SUJET, { delay: 25 });
  await pause(300);

  // Corps (CKEditor 5)
  await g1.cliquer(champCorps);
  for (const [i, ligne] of CORPS.entries()) {
    if (ligne) await page1.keyboard.type(ligne, { delay: 12 });
    if (i < CORPS.length - 1) await page1.keyboard.press("Enter");
  }
  await pause(800);

  // Sécurité : le mail ne part que vers ta propre adresse, et seulement si tout est bien rempli
  const verif = {
    destinataire: (await dialogue.locator("md-chip").filter({ hasText: /graine/i }).count()) >= 1
      && (await dialogue.locator("md-chip").count()) === 1,
    sujet: (await champSujet.inputValue()) === SUJET,
    corps: (await champCorps.innerText()).includes("mot de passe"),
  };
  if (!verif.destinataire || !verif.sujet || !verif.corps) {
    throw new Error(`Saisie incomplète, envoi annulé (${JSON.stringify(verif)})`);
  }

  await g1.cliquer(boutonEnvoyer);
  await page1.getByText("Votre courriel a été envoyé").waitFor({ timeout: 20_000 });
  await pause(1500);
  top("faux phishing envoyé");
} catch (e) {
  await signalerEchec(page1, `${SORTIE}/echec-partie1.png`);
  throw e;
}
const video1 = page1.video();
await contexte1.close();
await rename(await video1.path(), `${SORTIE}/partie1.webm`);

// ---------- Attente de la détection (non filmée) ----------
// Journal de TriLama : « UID ... -> PHISHING SUSPECT (...) : <sujet> » si le détecteur l'a repéré
const { execSync } = await import("node:child_process");
const limite = Date.now() + 15 * 60_000;
let ligneJournal = null;
while (!ligneJournal && Date.now() < limite) {
  try {
    const journal = execSync("docker compose logs --since 40m triage", { cwd: new URL("..", import.meta.url).pathname, encoding: "utf8" });
    ligneJournal = journal.split("\n").find((l) => MOTIF_REF.test(l) && l.includes("->")) ?? null;
  } catch {}
  if (!ligneJournal) await pause(15_000);
}
if (!ligneJournal) throw new Error("TriLama n'a pas traité le mail en 15 minutes. Vérifie : docker compose logs --tail 30 triage");
if (!ligneJournal.includes("PHISHING SUSPECT")) {
  throw new Error(`Le mail n'a pas été détecté comme phishing : ${ligneJournal.trim()}`);
}
await pause(5_000); // laisse l'étiquette IMAP se poser
top("phishing détecté par TriLama");

// ---------- Partie 2 : le mail est resté dans la boîte, étiqueté ----------
const contexte2 = await navigateur.newContext({ ...reglagesContexte(SORTIE), storageState: session });
await masquerAutresMails(contexte2);
await afficherCurseur(contexte2);
const page2 = await contexte2.newPage();
const g2 = gestes(page2);
try {
  await ouvrirBoite(page2);
  await pause(1500);
  await g2.cliquer(lignes(page2).first());
  const etiquette = page2.getByText("Phishing suspect", { exact: true }).filter({ visible: true }).first();
  await etiquette.waitFor({ timeout: 15_000 });
  await pause(800);
  await g2.deplacerVers(etiquette);
  await pause(2500);
  // On montre le lien piégé, sans cliquer dessus
  const lien = page2.getByText("univ-r0uen-login.xyz").filter({ visible: true }).first();
  if (await lien.isVisible().catch(() => false)) {
    await g2.deplacerVers(lien);
    await pause(2500);
  }
  top("étiquette affichée");
} catch (e) {
  await signalerEchec(page2, `${SORTIE}/echec-partie2.png`);
  throw e;
}
const video2 = page2.video();
await contexte2.close();
await rename(await video2.path(), `${SORTIE}/partie2.webm`);
await navigateur.close();
top("terminé");
