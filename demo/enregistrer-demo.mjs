// Enregistre la démo de TriLama dans le webmail SOGo de l'université.
//
// Déroulé : connexion (non filmée) -> partie 1 filmée : écriture et envoi d'un faux refus
// -> attente du tri (non filmée) -> partie 2 filmée : le mail arrive dans « Candidatures stage »
// avec l'étiquette « Stage - Refus ».
// Seul le dossier « Candidatures stage » est affiché : aucun autre mail n'apparaît à l'écran.

import { readFileSync } from "node:fs";
import { rename } from "node:fs/promises";
import { lancerNavigateur, reglagesContexte, afficherCurseur, gestes, pause, chrono, signalerEchec } from "./commun.mjs";

const SORTIE = process.env.SORTIE ?? "./tmp";
const WEBMAIL = "https://webmail.univ-rouen.fr/SOGo/";
// Référence unique à chaque lancement : on repère CE mail précisément (la liste SOGo est virtualisée,
// compter les lignes n'est pas fiable)
const REF = new Date().toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Paris" }).replace(":", "");
const SUJET = `Votre candidature au poste de stagiaire développeur (réf. ${REF})`;
const CORPS = [
  "Bonjour,",
  "",
  "Nous vous remercions de l'intérêt porté à notre entreprise.",
  "Après étude de votre dossier, nous avons le regret de vous informer que votre candidature n'a pas été retenue.",
  "",
  "Cordialement,",
  "Le service RH",
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
const DOSSIER = `${base}Mail/view#!/Mail/0/Candidatures%252520stage`;
const session = await connexion.storageState();
await connexion.close();
top("connecté");

async function ouvrirDossier(page) {
  await page.goto(DOSSIER);
  await page.getByText("message(s)").first().waitFor({ timeout: 30_000 });
  await page.evaluate(() => document.fonts.ready);
  await pause(800);
}

// Lignes du dossier qui portent le sujet du faux refus (les tests précédents compris)
const lignes = (page) => page.locator("md-list-item, .sg-message-list-item, [role='listitem']").filter({ hasText: SUJET });
let dejaPresents = 0;

// ---------- Partie 1 : envoi du faux refus ----------
const contexte1 = await navigateur.newContext({ ...reglagesContexte(SORTIE), storageState: session });
await afficherCurseur(contexte1);
const page1 = await contexte1.newPage();
const g1 = gestes(page1, { frappe: 25 });
try {
  await ouvrirDossier(page1);
  dejaPresents = await lignes(page1).count();
  await pause(1200);

  // Bouton d'écriture : au survol, deux petits boutons apparaissent au-dessus du bouton vert.
  // On amène la souris sur celui qui écrit dans la page, puis on le déclenche directement
  // (le menu se referme parfois avant qu'un clic souris n'arrive).
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

  // Sélecteurs relevés dans SOGo (fenêtre d'écriture = md-dialog).
  // Attention : le champ destinataire change d'aria-label quand il a le focus, on le vise donc
  // par son attribut name (input-NN), qui ne change pas. CC et CCI existent mais sont masqués.
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
  // SOGo ouvre une liste de suggestions : on clique la suggestion (Entrée ne la valide pas toujours)
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

  // Sujet (visé par son name : peu importe que l'ajout du destinataire ait décalé la mise en page)
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

  // Sécurité : rien n'est envoyé si un champ est mal rempli
  const verif = {
    destinataire: (await dialogue.locator("md-chip").filter({ hasText: /graine/i }).count()) >= 1
      && (await dialogue.locator("md-chip").filter({ hasText: "candidature" }).count()) === 0,
    sujet: (await champSujet.inputValue()) === SUJET,
    corps: (await champCorps.innerText()).includes("pas été retenue"),
  };
  if (!verif.destinataire || !verif.sujet || !verif.corps) {
    throw new Error(`Saisie incomplète, envoi annulé (${JSON.stringify(verif)})`);
  }

  await g1.cliquer(boutonEnvoyer);
  await page1.getByText("Votre courriel a été envoyé").waitFor({ timeout: 20_000 });
  await pause(1500);
  top("faux refus envoyé");
} catch (e) {
  await signalerEchec(page1, `${SORTIE}/echec-partie1.png`);
  throw e;
}
const video1 = page1.video();
await contexte1.close();
await rename(await video1.path(), `${SORTIE}/partie1.webm`);

// ---------- Attente du tri (non filmée) ----------
// On lit directement le journal de TriLama : plus fiable que de scruter la liste du webmail
const { execSync } = await import("node:child_process");
const limite = Date.now() + 12 * 60_000;
let trie = false;
while (!trie && Date.now() < limite) {
  try {
    const journal = execSync("docker compose logs --since 30m triage", { cwd: new URL("..", import.meta.url).pathname, encoding: "utf8" });
    trie = journal.split("\n").some((l) => l.includes(`réf. ${REF}`) && l.includes("->"));
  } catch {}
  if (!trie) await pause(15_000);
}
if (!trie) throw new Error("TriLama n'a pas traité le mail en 12 minutes. Vérifie : docker compose logs --tail 30 triage");
await pause(5_000); // laisse le déplacement IMAP se terminer
top("mail trié par TriLama");

const ligne = (page) => lignes(page).first();
// ---------- Partie 2 : le mail est rangé et étiqueté ----------
const contexte2 = await navigateur.newContext({ ...reglagesContexte(SORTIE), storageState: session });
await afficherCurseur(contexte2);
const page2 = await contexte2.newPage();
const g2 = gestes(page2);
try {
  await ouvrirDossier(page2);
  await pause(1500);
  await g2.cliquer(ligne(page2));
  const etiquette = page2.getByText("Stage - Refus", { exact: true }).filter({ visible: true }).first();
  await etiquette.waitFor({ timeout: 15_000 });
  await pause(800);
  await g2.deplacerVers(etiquette);
  await pause(3500);
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
