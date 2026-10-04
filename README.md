# AnkerGames RSS Generator

Feed RSS non ufficiale per [AnkerGames.net](https://ankergames.net/), ospitato su GitHub Pages e aggiornato ogni 6 ore con GitHub Actions. Il link `feed.xml` si aggiunge a Feedly (o a qualsiasi lettore RSS).

## File del progetto

| File | A cosa serve |
|---|---|
| `scraper.py` | Legge il sito, aggiorna `seen.json` e genera `feed.xml` |
| `requirements.txt` | Dipendenze Python |
| `index.html` | Pagina con link al feed, pulsante Copia e "Apri in Feedly" |
| `.github/workflows/rss_generator.yml` | Automazione (ogni 6 ore + avvio manuale) |
| `seen.json`, `feed.xml`, `.keepalive` | Generati dal workflow, non vanno creati a mano |

## Installazione (anche da telefono)

1. Crea un repository **pubblico** su GitHub (Pages gratuito richiede repo pubblico).
2. **Add file > Upload files** e carica `scraper.py`, `requirements.txt`, `index.html`, `README.md`.
3. Il workflow va in una cartella nascosta, quindi crealo a mano: **Add file > Create new file**, nel nome scrivi esattamente
   `.github/workflows/rss_generator.yml` (digitando `/` GitHub crea le cartelle), incolla il contenuto del file e fai **Commit**.
4. **Settings > Pages**: *Source* = `Deploy from a branch`, *Branch* = `main`, cartella `/ (root)`, poi **Save**.
5. **Settings > Actions > General > Workflow permissions**: se vedi l'opzione, scegli *Read and write permissions* (il workflow li richiede già nel file, ma alcune organizzazioni li bloccano).
6. **Actions > Genera feed RSS AnkerGames > Run workflow**.
7. Apri il run e controlla il log dello step *Genera feed*: deve dire `Feed generato: N giochi...`.
8. Dopo 1-2 minuti il feed è online su `https://TUONOME.github.io/NOMEREPO/feed.xml`. La pagina `https://TUONOME.github.io/NOMEREPO/` mostra il link già pronto, con il pulsante **Apri in Feedly**.

## Se qualcosa non funziona

- **Log con `HTTP 403`**: il sito blocca i server di GitHub (protezione Cloudflare). Lo scraper non può aggirarlo; serve un'altra strada (per esempio eseguirlo da un dispositivo tuo).
- **Log con `0 giochi trovati`**: il sito ha una struttura diversa dal previsto. Il log stampa i primi link e l'inizio dell'HTML: mandali per aggiornare lo scraper. Il feed esistente non viene toccato.
- **Il feed non si aggiorna**: GitHub disattiva i workflow schedulati dopo 60 giorni di inattività. Il workflow fa un commit mensile per evitarlo, ma se succede riattivalo da **Actions**.
- **Ordine strano / giochi vecchi come nuovi**: lo scraper legge `https://ankergames.net/recent-updates`. Se aggiungi altre pagine in `SOURCES` (per esempio la home, che mescola Trending e Top), possono comparire giochi vecchi come novità.

## Personalizzazione

In cima a `scraper.py`: `SOURCES` (pagine da leggere), `MAX_ITEMS` (quanti giochi tenere), `FEED_TITLE`, `FEED_DESC`.
