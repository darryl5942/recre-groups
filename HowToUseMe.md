# How to use Recre Groups 🧗

This app takes a Telegram poll, finds the **first 20 people** who voted for a session, creates that session's group, adds them, and sends the invite link to anyone who couldn't be added.

---

## Part 1: First-time setup (once per computer, about 10 minutes)

### Step 1: Install Python
1. Go to <https://www.python.org/downloads/> and download Python (version 3.10 or newer).
2. Run the installer.
   - **Windows:** on the first screen, tick **"Add python.exe to PATH"**, then click **Install Now**.
   - **Mac:** just click through the installer.

### Step 2: Download the app
1. Go to <https://github.com/darryl5942/recre-groups>.
2. Click the green **Code** button, then **Download ZIP**.
3. Unzip it somewhere easy to find, e.g. your Desktop or Documents.

### Step 3: Start the app
- **Windows:** double-click **`start.bat`** in the app's folder.
- **Mac:** open **Terminal** and type `cd ` (with a space after it). Drag the app's folder into the Terminal window, press **Enter**, then type `sh start.sh` and press **Enter**.

A window with text opens. **Keep it open while you use the app.** Closing it stops the app.
The first start takes a minute or two to set up. Then your browser opens at <http://127.0.0.1:5050>.

### Step 4: Get your Telegram API keys
These let the app log in to your account. Each person gets their own.
1. Go to <https://my.telegram.org> and enter your phone number with the country code (e.g. `+6591234567`).
2. Telegram sends a code **to your Telegram app** (not by SMS). Enter it.
3. Click **API development tools** and fill in:

   | Field | What to put |
   |---|---|
   | App title | `SMU Climb Poll` (at least 5 characters, don't include the word "Telegram") |
   | Short name | `smuclimbpoll` (letters and numbers only, no spaces or hyphens) |
   | URL | leave empty |
   | Platform | **Desktop** |
   | Description | `Creates session groups from poll votes for my climbing club.` |

4. Click **Create application**.
5. Copy the **App api_id** (a number) and the **App api_hash** (a long string).

> 🔒 Treat the api_hash like a password. Paste it only into the app, never into a chat.

### Step 5: Enter the keys in the app
1. On the app's **One-time setup** page, paste the **API id** and **API hash**.
2. Click **Save and continue**.

### Step 6: Log in to Telegram
1. Enter your phone number with the country code, then click **Send login code**.
2. Enter the code Telegram sends to your Telegram app, then click **Log in**.
3. If the page asks for your **2-step verification password**, enter the password you set yourself in
   Telegram (**Settings → Privacy and Security → Two-Step Verification**). It isn't the code you just got.
   - Forgot it? In Telegram, tap **Forgot password?** on that same settings screen.

✅ Setup is done. From now on, just start the app (Step 3) and you'll already be logged in.

---

## Part 2: Every week

### Step 1: Post the poll
1. Create the poll in the club chat as usual, e.g.
   ```
   WEEK 11 RECRE 🧗
   28 Oct 730pm-930pm @B+ Aperia w/Darryl
   30 Oct 4pm-6pm @BP TS w/Irina
   ```
2. ⚠️ **Turn OFF "Anonymous Voting"**, otherwise nobody can see who voted.
3. **Vote in the poll yourself** (any option, or close the poll later). Telegram only shows who voted
   once you've voted. Your own vote is **never** counted toward the 20.

> Tip: write options as `<date> <time> @<place> w/<name>` and the app names groups automatically,
> e.g. `28 Oct Recre @ B+ Aperia`.

### Step 2: Start the app
Double-click **`start.bat`** (or run `sh start.sh` on Mac). The browser opens.

### Step 3: Choose the chat
1. In **Chat with the polls**, start typing the chat's name and choose it from the suggestions.
   - Part of a name works if only one chat matches.
   - You can also paste an `@username` or a `t.me/...` link.
2. Click **Show polls**. The latest polls in that chat appear, from anyone, with vote counts for each option.

The app remembers this chat for next time.

### Step 4: Click a session option
Click an option, e.g. **28 Oct 730pm-930pm @B+ Aperia w/Darryl**. You'll see:
- **Every voter in the order they voted**, with a **cut-off line after #20**
- **The group name**: change it if you like, then click **Refresh**
- **Whether the group already exists**:
  - *"No group for this option yet"*: a new group will be created.
  - *"A group named … already exists"*: only new people will be added to it.
- **Each person's status**: *Will be added*, *Already in group*, *Link sent earlier* or *Not in first 20*

### Step 5: Check the invite message, then press the button
1. The **Invite link message** box holds the message sent to people who **can't be added directly**. Edit it if you like.
   You can use these placeholders:
   - `{name}`: their first name
   - `{option}`: the session option
   - `{title}`: the group name
   - `{link}`: the invite link
2. Press **Create group and add N people** (or **Add N new people to the group**).
3. ⏳ A progress page shows each step as it happens, e.g. *"Adding 7 of 20: Alex"*. It takes about 5 seconds per person.
   That's on purpose, so Telegram doesn't flag your account. The results appear by themselves when it's done.

### Step 6: Check the results
The results page shows each person's final status:

| Status | Meaning | What you do |
|---|---|---|
| **Added** | Added to the group just now | Nothing |
| **Already in group** | Was already in it | Nothing |
| **Invite link sent** | Couldn't be added (privacy settings), so they got the link by private message | Nothing, they just need to tap it |
| **NOT REACHED** (highlighted) | Couldn't be added *and* couldn't be messaged | Send them the invite link yourself (it's shown on the page) |
| **Not in first 20** (greyed out) | Voted after the first 20 | Nothing, unless you want to bring them in yourself |

Click **Download Excel sheet** to get the full list with positions, handles and vote times.

### Step 7: Send or schedule the welcome messages
This is a separate step, so you can add everyone first and send the messages whenever you're ready.
Click **Next: welcome messages →** on the results page. You can also get there later from **Groups** at the top of any page.

The app can post three things in the group:
1. **The welcome message**, pinned: date, location, nearest MRT, things to bring and safety rules
2. **The meeting message**, e.g. "meet us at GU @ 4.00pm or in school at Bencoolen Exit C @ 3.30pm"
3. **The "Meet where!!!" poll**, with one option per meeting point

To set them up:
- **Fill in the session details:** day, date, time, location, short name (e.g. `GU`), nearest MRT, school meeting point and meeting time.
  Most of these are prefilled from the poll option. The meeting time defaults to 30 minutes before the start.
  - Boxes tagged **EXAMPLE** couldn't be read from the poll option, so they show sample values. Replace them.
    If you try to send with example values still in, the app asks you to confirm first.
  - Boxes outlined in yellow are empty.
- **The messages update as you type.** You can also edit the final text directly, including the poll options.
  To undo your edits, click **↺ redo from template**. Leave a message empty to skip it.
- **Make the location clickable (optional):** in Google Maps, find the gym, tap **Share → Copy link**, and paste it into **Map link**.
  In Telegram, the location name (e.g. "Ground Up") becomes a link that opens the map. On this page it looks like
  `[Ground Up](https://maps.app.goo.gl/...)`, but in Telegram only "Ground Up" shows. You can add your own links anywhere the same way.
  (Polls can't have links, so they just show the name.)
- **The app remembers each place.** Once you've entered the MRT, short name, map link and meeting point for a gym, they're prefilled the next time.
- **To change the default wording** (e.g. "mid terms coming up"), click **Welcome templates** at the top of the page.
  Words in `{curly brackets}` are filled in for each session.

Then choose **when**:
- **Send now:** everything is posted straight away and the welcome message is pinned.
- **Schedule for** a date and time: Telegram sends the messages at that time by itself, so your computer can be off.
  - In the group, the scheduled messages wait under the **clock icon** next to the message box. You can edit, send early or cancel them there.
  - Telegram can't pin a message before it's sent, so the app pins the welcome message the first time it's open after the scheduled time.
    If your computer was off, just open the app afterwards and it pins it within a minute.

The page lists what's already been sent or scheduled for that group, so you don't send things twice by accident.

### Step 8: Do the other session
Go back with **← All polls** and repeat Steps 4–7 for the other option.

---

## Part 3: Running it again during the week

More people voted since your last run? Just do Steps 2–6 again for the same option.
The welcome messages don't need sending again: new people see the pinned one when they join.
- It **finds the existing group** and only adds new people who are in the top 20.
- It **won't message anyone twice**.
- Each run adds a **new tab** to that group's Excel sheet, so you can compare positions over time.

Example: on the first run 10 people had voted, so all 10 were added. By the second run 25 have voted,
so the second run adds #11–20. #21–25 aren't added.

**Cancellations:** if someone in the top 20 changes their vote, the next run shows the new order,
and whoever moved up into the top 20 gets added. The app **never removes anyone**. Do that yourself in Telegram if needed.
Someone who removes their vote and votes again moves to the back of the queue, because Telegram resets their vote time.

---

## Part 4: Troubleshooting

| Problem | Fix |
|---|---|
| *"Vote in this poll yourself first"* | Vote on any option in Telegram, then refresh the page |
| *"This poll is anonymous"* | That poll can't be used. Post a new one with Anonymous Voting off |
| *"Telegram says slow down"* | Wait the number of minutes shown, then run it again. It picks up where it stopped |
| *"Several chats match"* | Type more of the chat's name |
| My poll isn't in the list | Check you chose the right chat. Only the latest 10 polls are shown |
| The page won't open | Check the start window is still open, then go to <http://127.0.0.1:5050> |
| `start.bat` closes straight away | Python isn't installed or wasn't added to PATH. Reinstall it and tick "Add python.exe to PATH" |
| I want to use a different Telegram account | Click **Log out** at the top right, then log in again |

---

## Part 5: Getting updates

When the app is updated on GitHub:
1. Download the ZIP again (Part 1, Step 2).
2. **Copy your old `data` folder into the new folder.** That keeps you logged in and keeps the app's
   memory of which groups it made. Copy `exports` too if you want your old sheets.

If you downloaded it with `git clone`, just run `git pull` in the folder instead.

---

## ⚠️ Keep these private
- **`data/`** holds your Telegram login. Anyone with this folder can use your account. Never send it to anyone or upload it.
- **`exports/`** holds members' Telegram handles. Share these sheets only with other captains.

The app **creates both folders by itself** the first time it starts, so there's nothing to set up.
Each captain's computer gets its own: downloading the app from GitHub never includes anyone else's login, chats or sheets,
because both folders are excluded from git and never get uploaded.
