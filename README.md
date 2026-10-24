# Recre Groups 🧗

A small local web page that turns a Telegram poll into session groups.

1. Pick the poll (e.g. *WEEK 11 RECRE 🧗*) and one option (e.g. *28 Oct 730pm-930pm @B+ Aperia w/Darryl*).
2. It takes the **first 20 people who voted** for that option, ordered by when they voted.
3. It creates the group *28 Oct Recre @ B+ Aperia*, or reuses it if it already exists.
4. It adds those people. Then it checks who actually got in, and privately sends the invite link to anyone who couldn't be added.
5. It saves an Excel sheet of every voter with their position and status in `exports/`, with one tab per run.

You can run it as often as you like. People already in the group, or already sent the link, are skipped.
So if 10 people had voted on the first run and 25 by the second run, the second run adds voters #11–20.

It logs in as **your own Telegram account**, not a bot, because Telegram bots can't create groups.

## Setup (once per computer)

1. Install **Python 3.10 or newer** from [python.org](https://www.python.org/downloads/).
   On Windows, tick **"Add python.exe to PATH"** in the installer.
2. Download this folder (on GitHub: **Code → Download ZIP**, then unzip it).
3. Start it:
   - **Windows:** double-click `start.bat`
   - **Mac:** open Terminal in this folder and run `sh start.sh`
4. The page opens at <http://127.0.0.1:5050>. Follow its steps:
   - Get your own **API id and hash** from [my.telegram.org](https://my.telegram.org) → *API development tools*.
   - Log in with your phone number and the code Telegram sends you.

From then on, just run `start.bat` / `start.sh` again.

## Every week

1. Post the poll in the club chat. **Turn off "Anonymous Voting"**, otherwise nobody can see who voted.
2. Run the app, choose the chat, then click the poll option.
3. Check the group name and the voter list, then press **Create group** (or **Add new people**).
4. Press **Download Excel sheet** to get the list of voters and positions.

Telegram only shows a poll's voters once you've voted in it yourself (or it's closed).
Your own vote is never counted toward the 20.

## Good to know

- **Privacy settings:** people who only let contacts add them to groups can't be added. They get the invite link by private message instead.
  If they also block messages from strangers, the sheet marks them **NOT REACHED**, so you can send the link yourself.
- **It's slow on purpose:** it waits a few seconds per person. Adding or messaging lots of strangers quickly can get your account temporarily limited by Telegram.
- **Cancellations** aren't handled automatically. If someone in the top 20 changes their vote, the next run shows the new order in the sheet, and the new #20 gets added. Remove people yourself if needed.
  If someone changes their vote and then votes again, Telegram resets their vote time, so they move to the back of the queue.
- **Two captains:** each captain uses their own login, and each computer remembers its own groups.
  If a group with the exact same name already exists in your chats, the app tells you and reuses it.
  Still, agree on which captain runs which option, so the same session doesn't get two groups.
- **Keep the `data/` folder private.** It holds your Telegram login. It's excluded from git, so it never gets uploaded.
