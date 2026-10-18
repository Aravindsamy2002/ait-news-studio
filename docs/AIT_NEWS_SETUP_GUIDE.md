# AIT NEWS 24/7 — Full Setup Guide

YouTube channel create pannuradhula irundhu 24/7 live stream + automatic uploads varaikkum, ellaa steps-um order-la.
Ovvoru part mudinjadhum ✅ tick pannikonga.

| Part | Enna | Evlo neram |
|---|---|---|
| 1 | Channel create + branding | 10 min |
| 2 | Phone verify | 2 min |
| 3 | Channel settings | 10 min |
| 4 | Live streaming enable + stream key | 5 min + **24 mani neram wait** |
| 5 | VM-la AIT service setup | 15 min |
| 6 | Google Cloud API (auto-upload-ku) | 15 min |
| 7 | PC-la login → token-a VM-ku copy | 5 min |
| 8 | Go live + check | 10 min |
| 9 | API audit (videos public aaga) | form 15 min + Google review |

> **Mukkiyam:** Part 2 (phone verify) and Part 4 (live enable)-a **inniku-e** pannidunga. Live streaming YouTube 24 mani neram kazhichu dhaan on pannum. Andha wait-la matha parts-a mudichidalaam.

---

## Part 1 — Channel create + branding

1. youtube.com → profile picture → **Create a channel** (neenga ippo indha screen-la dhaan irukkeenga).
2. **Name:** `AIT NEWS 24/7`
3. **Handle:** `@AITNEWS247` (green tick vandha available)
4. **Select picture:** `assets/branding/channel_picture.png` upload pannunga.
5. **Create channel** click.

   ℹ️ Idhu un Gmail account-la manage aagura **Brand Account**-ah create aagum. Nalladhu, later vera managers-ai serkkalaam.

6. **Banner + watermark** (YouTube Studio → **Customization** → **Branding**):
   - Banner image: `assets/branding/channel_banner.png` (2560×1440, text ellam safe area-kulla irukku)
   - Video watermark: `assets/branding/watermark.png` → Display time: **Entire video**
   - **Publish** click.

- [ ] Part 1 done

---

## Part 2 — Phone verify

1. **youtube.com/verify** open pannunga (AIT NEWS 24/7 channel select aagi irukkanum).
2. Country: India → SMS → code enter pannunga.

Idhu unlock pannuradhu: **live streaming**, **custom thumbnails** (auto-upload thumbnails-ku venum), 15 nimishathukku mela neelamaana videos.

- [ ] Part 2 done

---

## Part 3 — Channel settings

**YouTube Studio → Customization → Basic info**

- **Description** (copy-paste pannalaam):
  ```
  AIT NEWS 24/7 brings you the biggest stories in technology, artificial intelligence,
  cybersecurity and Big Tech — live, around the clock. Every story is sourced from
  established publications, with the original source linked in each video.
  ```
- **Links:** venumna website/Instagram add pannunga.
- **Contact info:** business email.

**YouTube Studio → Settings (keezha left corner)**

| Edam | Setting |
|---|---|
| General | Currency: INR |
| Channel → Basic info | Country: India · Keywords: `tech news, AI news, technology, cybersecurity, breaking news` |
| Channel → Advanced settings | Audience: **No, set this channel as not made for kids** |
| Upload defaults → Basic info | Visibility: Public · Tags: `AIT News, Tech News` |
| Upload defaults → Advanced settings | Category: **News & Politics** · Video language: **English** · Allow embedding: ✅ |

**Altered/synthetic content** kelvi varum bodhu: **No** select pannunga. YouTube rules-padi real person-a mimic pannaadha generic AI narration voice-ku disclosure compulsory illa. Namma videos real person-a fake panradhu illa, nadakkaadha scene-a kaattradhu illa.

- [ ] Part 3 done

---

## Part 4 — Live streaming enable + stream key

1. YouTube Studio → **Create** (mela right) → **Go live**.
2. First time-na "Enable live streaming" → **Enable**.
3. ⏳ **24 mani neram wait.** Andha nerathula Part 5, 6, 7 pannidalaam.
4. 24 mani nerathukku apram: **Create → Go live → Stream** tab:

| Setting | Value |
|---|---|
| Title | `AIT News LIVE: Tech & AI news, 24/7` (system idhai top story-padi thaanaa maathum) |
| Description | Part 3 description-ai paste pannunga |
| Category | News & Politics |
| Visibility | Public |
| Audience | Not made for kids |
| Stream latency | **Normal latency** (best quality) |
| Enable DVR | ✅ |
| Additional settings → **Auto-start** | ✅ ON |
| Additional settings → **Auto-stop** | ❌ **OFF** (OFF-la illana, network chinna break aanaa kooda stream end aagidum) |

5. **Stream key** → **Copy**.

   ⚠️ Stream key = password maadhiri. Yaarukkum anuppaadheenga, chat-la paste pannaadheenga, screenshot edukkaadheenga. Leak aanaa Studio-la **Reset** pannidunga.

   ⚠️ **AIT channel-oda key mattum** dhaan use pannanum. VM-la odura BTC Live Desk stream-oda key thani, adha touch pannaadheenga.

- [ ] Part 4 done (stream key copy pannitten)

---

## Part 5 — VM-la AIT service setup

Code already VM-la `~/ait_news_studio`-la irukku. PowerShell-la VM-ku login pannunga:

```powershell
ssh -i $env:USERPROFILE\.ssh\ssh-key-2026-10-09.key ubuntu@<VM_IP>
```

VM-la:

```bash
cd ~/ait_news_studio
bash deploy/setup_oracle.sh
```

Idhu pannuradhu: venv + packages, Kokoro voice model, `/etc/ait-news/env` (secrets file), `ait-news` systemd service. Ollama install aagaadhu (analysis off).

Stream key-a secrets file-la podunga:

```bash
sudo nano /etc/ait-news/env
```

`YOUTUBE_STREAM_KEY=` line-la, `=`-ku apram Part 4-la copy panna key paste pannunga → **Ctrl+O**, **Enter** (save) → **Ctrl+X** (exit).

⚠️ Service-a **innum start pannaadheenga.** Part 8-la start pannalaam.

- [ ] Part 5 done

---

## Part 6 — Google Cloud API (automatic uploads-ku)

Ellam free. Card/billing thevai illa.

1. **console.cloud.google.com** → mela project dropdown → **New project** → name: `AIT News Publisher` → **Create** → andha project-a select pannunga.
2. **APIs & Services → Library** → "YouTube Data API v3" search → **Enable**.
3. **Google Auth Platform** (illana "OAuth consent screen") → **Get started**:
   - App name: `AIT News Publisher`
   - User support email: un Gmail
   - Audience: **External**
   - Contact email: un Gmail → **Create**
4. **Audience** → **Test users** → **Add users** → un Gmail add pannunga.
5. Adhe **Audience** page-la → **Publish app** → **Confirm**. Status **"In production"**-nu kaattanum.

   ⚠️ Idhu romba mukkiyam. **"Testing"**-laye vittaa login token **7 naal-la expire aagi**, uploads silent-ah nikkidum.

6. **Clients** (illana Credentials) → **Create client** → Application type: **Desktop app** → Name: `AIT VM` → **Create** → **Download JSON**.
7. Download aana file-a rename pannunga: `client_secret.json` → project folder-la podunga:
   `C:\Users\aravi\Downloads\claude\ait_news_studio\client_secret.json`

   ⚠️ Idhuvum secret file dhaan. Git-la poga koodaadhu (`.gitignore`-la already irukku).

- [ ] Part 6 done

---

## Part 7 — PC-la login → token-a VM-ku copy

PC-la PowerShell:

```powershell
cd C:\Users\aravi\Downloads\claude\ait_news_studio
pip install -r requirements.txt
python youtube_uploader.py auth --client-secret client_secret.json
```

Browser open aagum:

1. Un Gmail select pannunga.
2. "Choose an account or brand account" screen vandha → **AIT NEWS 24/7** select pannunga. Personal account illa!
3. "Google hasn't verified this app" warning varum → **Advanced** → **Go to AIT News Publisher (unsafe)**. Idhu neenga create panna un app dhaan, safe.
4. Ella permissions-kum **Continue / Allow**.

Terminal-la `Saved token to ...secrets\youtube_token.json` varum. Correct channel-aa nu check pannunga:

```powershell
python youtube_uploader.py whoami
```

Output-la `Channel: AIT NEWS 24/7` varanum. Vera channel peyar vandha `secrets\youtube_token.json`-a delete panni, step 2-la correct channel select panni thirumba pannunga.

Token-a VM-ku copy pannunga (owner mattum padikka mudiyura permissions-la):

```powershell
ssh -i $env:USERPROFILE\.ssh\ssh-key-2026-10-09.key ubuntu@<VM_IP> "mkdir -m 700 -p ~/ait_news_studio/secrets"
scp -i $env:USERPROFILE\.ssh\ssh-key-2026-10-09.key secrets\youtube_token.json ubuntu@<VM_IP>:ait_news_studio/secrets/youtube_token.json
ssh -i $env:USERPROFILE\.ssh\ssh-key-2026-10-09.key ubuntu@<VM_IP> "chmod 600 ~/ait_news_studio/secrets/youtube_token.json && cd ~/ait_news_studio && .venv/bin/python youtube_uploader.py whoami"
```

Kadaisi command-la VM-um `Channel: AIT NEWS 24/7` nu sollanum.

- [ ] Part 7 done

---

## Part 8 — Go live + check

Part 4-oda 24 mani neram wait mudinjirukkanum, stream key Part 5-la pottirukkanum.

VM-la:

```bash
sudo systemctl start ait-news
journalctl -u ait-news -f
```

Log-la idhellam varanum (Ctrl+C pannina log paakuradhu mattum nikkum, service odikkittu irukkum):

```
Autopilot running: 1 render workers, rotation of 15 stories
Stream encoder started (copy mode, no re-encode)
On air: standby.mp4
Feeds refreshed: NN fresh stories
Queued render: ...
Clip ready: ...
[youtube] Uploaded https://youtu.be/...
[youtube] Live title -> AIT News LIVE: ...
```

**Check list:**

- [ ] YouTube Studio → Go live → stream **"Excellent"/"Good"** health-la live-ah irukku
- [ ] Mudhal ~2 nimisham "AIT NEWS — STAY TUNED" standby slate, apram real news clips varudhu
- [ ] Live title top story-padi maarudhu
- [ ] Studio → **Content**-la story videos upload aagudhu (audit varaikkum **Private**-ah dhaan irukkum, Part 9 paarunga)
- [ ] **BTC Live Desk stream health** innum "Excellent/Good"-la dhaan irukku (rendu streams-um ore VM-la odudhu)

- [ ] Part 8 done

---

## Part 9 — API audit (uploaded videos public aaga)

Puthu API project-la upload aagura videos Google audit pass aagura varaikkum **private-ah lock** aagum. Live stream-ku indha problem illa, adhu Part 8-la irundhe public-ah dhaan odum.

1. **YouTube API Services – Audit and Quota Extension Form**: https://support.google.com/youtube/contact/yt_api_form
2. Fill pannunga:
   - Project: `AIT News Publisher` (project number Google Cloud Console home-la irukkum)
   - Use case: "Automated uploads of our own news videos to our own channel (AIT NEWS 24/7) and updating our own live broadcast title. Single channel, no third-party users."
   - API client: Desktop app, internal use only
3. Submit → Google reply-ku wait (sila naatkal mudhal sila vaarangal varaikkum aagalaam).

Approve aagura varaikkum: Studio → Content-la important videos-a neenga manual-ah **Public** pannalaam.

- [ ] Part 9 submitted
- [ ] Part 9 approved

---

## Daily use — commands

VM-la (`ssh ... ubuntu@<VM_IP>` apram):

| Enna venum | Command |
|---|---|
| Status paakka | `systemctl status ait-news` |
| Live log | `journalctl -u ait-news -f` |
| Kadaisi 100 log lines | `journalctl -u ait-news -n 100` |
| Restart | `sudo systemctl restart ait-news` |
| Stop | `sudo systemctl stop ait-news` |
| Reboot-la auto-start off | `sudo systemctl disable ait-news` |
| Upload aana videos list | `cat ~/ait_news_studio/output/youtube_uploads.json` |
| Disk usage | `df -h /` |

**Settings maatha** (`sudo nano /etc/ait-news/env`, save, apram `sudo systemctl restart ait-news`):

| Setting | Default | Arthham |
|---|---|---|
| `YOUTUBE_STREAM_KEY` | — | AIT live stream key |
| `RENDER_WORKERS` | `1` | Parallel renders (VM shared, adhanaala 1) |
| `YOUTUBE_UPLOADS` | `1` | `0` = story videos upload pannaadhu |
| `YOUTUBE_LIVE_TITLE` | `1` | `0` = live title auto-update off |
| `YOUTUBE_PRIVACY` | `public` | `unlisted` / `private` |
| `YOUTUBE_MAX_UPLOADS_PER_DAY` | `4` | Daily upload limit (puthu channel-ku kammiya; maasam maasam koottalaam) |
| `YOUTUBE_MIN_UPLOAD_GAP_MINUTES` | `120` | Rendu uploads-ku idaiyila minimum gap — burst upload pannave koodaadhu |
| `YOUTUBE_SHORTS` | `1` | Stories vertical Shorts-ah upload aagum (`0` = 16:9 video) |
| `BULLETIN_ENABLED` | `1` | Dhinamum oru long-form "Tech News Today" bulletin (4 slots-la 1) |
| `BULLETIN_HOUR_UTC` | `13` | Bulletin time (13 UTC = 18:30 IST = US kaalai 9) |
| `ANALYSIS_ENABLED` | `0` | "What it means" LLM segment (accuracy-kaaga off) |

---

## Problem vandha

| Problem | Enna pannanum |
|---|---|
| Studio "No data" / stream offline | `journalctl -u ait-news -n 50`. "Set YOUTUBE_STREAM_KEY" vandha Part 5 key check pannunga. Key reset pannirundha puthu key podunga. |
| Stream adikkadi stop aagudhu | Part 4 **Auto-stop OFF**-ah irukka nu check pannunga |
| `[youtube] No token at ...` | Part 7 token copy aagala; path `~/ait_news_studio/secrets/youtube_token.json` |
| `invalid_grant` / token expired | Part 6 step 5 "In production" pannala. Publish panni Part 7-a thirumba pannunga. |
| `Thumbnail not set ... phone-verified?` | Part 2 phone verify pannunga |
| `YouTube quota reached` | Normal; 6 mani nerathula thaanaa resume aagum |
| Videos ellam Private | Part 9 audit approve aagala; adhuvaraikkum manual-ah Public pannunga |
| BTC stream health kurayudhu | `RENDER_WORKERS=1` irukka nu check pannunga; innum problem-na sollunga, render-a innum kurachidalaam |

---

## Monetization (YPP) — later

- Requirement: **1,000 subscribers** + **4,000 public watch hours (last 12 maasam)**, illana 10M Shorts views (90 naal).
- YouTube "reused content" rules-padi, source text-a mattum padikkura channels-ku approval kashtam. Approval reject aanaa "what it means" analysis-a thirumba on pannalaam (`ANALYSIS_ENABLED=1`). Accuracy check-um thirumba pannanum.

---

## Files reference

| File | Edhukku |
|---|---|
| `assets/branding/channel_picture.png` | Channel profile picture (800×800) |
| `assets/branding/channel_banner.png` | Channel banner (2560×1440) |
| `assets/branding/watermark.png` | Video watermark (150×150) |
| `client_secret.json` (PC mattum) | Google OAuth client — **secret** |
| `secrets/youtube_token.json` (PC + VM) | Channel login token — **secret**, permissions 600 |
| `/etc/ait-news/env` (VM) | Stream key + settings — **secret** |
