# Runbook: stand up a new profile

Creates a new profile repository from a released core, with `toolboxctl.py init`. `init`
is the one subcommand that runs from a release archive instead of `core/`: a new profile
has no `core/` yet. It vendors the release the archive is into `core/`, then runs setup.

Every command below is pasteable as written. Where a command takes a value of yours, the
value is a synthetic example and a line under the command says "replace with yours". Use
the same values in every step.

| Example value | What it stands for |
|---|---|
| `acme-owner` | the GitHub owner of the new profile repository and of the core |
| `acme-profile` | the new profile repository |
| `acme-core` | the core repository |
| `v0.1.19` | a release tag that carries `init` |
| `acme-core-0.1.19` | the folder the release archive extracts to |
| `work` and `scratch` | two new folders side by side: one for the clone, one for the archive |

## Before you start

- These tools on the machine. The push gates the profile turns on run them, and a gate
  whose tool is missing refuses the push, so install them before the first push.

  | Tool | Why | Debian or Ubuntu | Windows (PowerShell) |
  |---|---|---|---|
  | `git` | everything | `sudo apt install git` | `winget install --id Git.Git` |
  | `python` (3) | setup, sync, the gates | `sudo apt install python3 python-is-python3` | `winget install --id Python.Python.3.12` |
  | PyYAML | reads `profile.yaml` | `sudo apt install python3-yaml` | `python -m pip install pyyaml` |
  | `gh`, signed in (`gh auth status`) | creates the repository | `sudo apt install gh` | `winget install --id GitHub.cli` |
  | `ruff` | the `ruff` gate | `sudo apt install pipx`, then `pipx install ruff` | `python -m pip install ruff` |
  | `shellcheck` | the `shellcheck` gate | `sudo apt install shellcheck` | `winget install --id koalaman.shellcheck` |
  | Node.js | the `eslint` and `typecheck` gates, only where the repository has JavaScript or TypeScript | `sudo apt install nodejs npm` | `winget install --id OpenJS.NodeJS.LTS` |

  On Linux, `python` has to be on `PATH`; `python-is-python3` does that. Open a new
  terminal after installing, so `PATH` is read again.
- The core repository and a release tag that carries `init`.
- Be ready to answer setup's questions at the console. Or write an answers file holding
  `identity:`, `source:`, `answers:`, the leak-gate keys (`personal`, `profile_name`,
  `leak_extra`, `not_onboarded`) and `targets:` (a list of the target repositories' folder
  names; without it `init` asks for them at the console), and pass it with `--answers answers.yaml`.
  Locking the push gates always needs a person typing `yes` at the console, never piped
  input, and `init` asks for it in each case below.
  - You answer setup at the console: setup asks to lock the gates right after your answers.
  - You pass an answers file with `targets:`: setup skips the lock, and `init` asks for it
    before it commits the profile. With no console, `init` stops there, keeps what it wrote,
    and prints the command to lock the gates, commit and render.
  - You pass an answers file without `targets:`: `init` first asks for the targets at the
    terminal, which needs stdin to be a terminal, then asks for the lock as above.
  - You add `--setup-only`: with console answers, setup still asks for the lock. With an
    answers file, nothing asks; the next steps tell you to run
    `python core/consent.py --profile . --init`.
- Any text editor works for `profile.yaml`. Notepad, nano and VS Code are all fine.

## Steps

1. **Create the empty private repository and give it a git identity and a `main` branch.**
   Shell: bash, PowerShell or any shell with `gh`. Folder: the new folder `work`.

   ```
   gh repo create acme-owner/acme-profile --private --clone
   ```

   Replace `acme-owner/acme-profile` with yours. Give it no `--add-readme`, `--license`
   or `--gitignore` option. The repository must be empty: setup refuses a folder that
   holds anything but `.git` and `core`.

   Cloning an empty repository prints `warning: You appear to have cloned an empty
   repository.` That warning is expected. It is not an error.

   Move into the clone.

   ```
   cd acme-profile
   ```

   Replace `acme-profile` with yours.

   A clean machine has no git identity, and the first commit fails without one. Set one
   for this repository only. Run these two commands, each with your own value:

   ```
   git config user.name "Dev Example"
   ```

   ```
   git config user.email "dev@acme.example"
   ```

   Replace `Dev Example` and `dev@acme.example` with yours. Use your own name and email,
   not the examples.

   A clean machine may also name its default branch `master`, and the push gates expect
   `main`. Name the branch `main` now.

   ```
   git checkout -b main
   ```

   If this reports that `main` already exists, you are on it and can go on. If you have
   already made a commit, run `git branch -M main` instead.

2. **Download a release archive into a scratch folder.** Shell: as above. Folder:
   `scratch`, a new folder next to `work`, outside the clone.

   A release is a tag. The release workflow creates no GitHub Release, so
   `gh release download` finds nothing. Fetch the tag's archive instead. The command
   writes the file itself; never redirect a download with `>`, which Windows PowerShell
   5.1 re-encodes as text, corrupting the archive.

   For a public core, in bash:

   ```
   curl -fL -o core.tar.gz https://github.com/acme-owner/acme-core/archive/refs/tags/v0.1.19.tar.gz
   ```

   Or in PowerShell (5.1 or 7):

   ```
   curl.exe -fL -o core.tar.gz https://github.com/acme-owner/acme-core/archive/refs/tags/v0.1.19.tar.gz
   ```

   Type `curl.exe`, not `curl`: in Windows PowerShell 5.1 `curl` is an alias for
   `Invoke-WebRequest`. Windows 10 and later ship `curl.exe` and `tar.exe`. With `-f`, a
   mistyped tag fails here instead of saving GitHub's error page as `core.tar.gz`.

   For a private core, use `gh`, in bash or PowerShell 7.4 or later only (5.1 corrupts the
   redirected archive):

   ```
   gh api repos/acme-owner/acme-core/tarball/v0.1.19 > core.tar.gz
   ```

   Replace `acme-owner/acme-core` and `v0.1.19` with yours.

   Extract it.

   ```
   tar -xzf core.tar.gz
   ```

   The archive holds one top-level folder. From `curl` it is named
   `<core-repo>-<tag without the leading v>`, for example `acme-core-0.1.19`; from
   `gh api` it is `<owner>-<core-repo>-<short sha>`, for example
   `acme-owner-acme-core-1a2b3c4`. List the folder to read its real name.

3. **Run `init`.** Shell: as above. Folder: `scratch`.

   ```
   python acme-core-0.1.19/toolboxctl.py init --profile ../work/acme-profile --source acme-owner/acme-core
   ```

   Replace `acme-core-0.1.19` with the folder from step 2, `../work/acme-profile`
   with the path to your clone, and `acme-owner/acme-core` with your core repository.

   `init` refuses, and changes nothing, if the folder is not a git work tree or already
   holds `core/` or `profile.yaml`. Otherwise it writes `core/` (with `core/VENDORED`
   recording the tag and commit) and `profile.yaml`, and prints a dry-run render.

   Setup asks its questions at the console, and after each answer prints one line saying
   where it goes. If it asks you to lock the push gates, type `yes`. If you stop setup
   part-way, delete `core/` in the clone and run this step again.

   After setup, `init` asks for your target repositories, as folder names beside the
   profile, one per line, and writes them in place of the example targets. It then
   commits the profile ("Create the profile"), renders the profile into itself, and
   commits the render ("Render the profile"). It does not push.

   If anything fails, or you stop it, after setup has finished, `init` keeps everything it
   wrote and prints the one step to run next. Run that step, then carry on from step 4.

   To stop after setup and do steps 4 and 5 by hand, add `--setup-only` to the command.

4. **Review.** Shell: as above. Folder: `work/acme-profile`.

   ```
   git log --oneline
   ```

   ```
   git status
   ```

   After a full `init`, the log shows the two commits and the tree is clean. Read
   `profile.yaml` in any editor, and go on to step 6.

   With `--setup-only`, nothing is committed yet. Replace the example targets
   (`example-app`, `example-scratch`) under `targets:` with your own repositories, then
   do step 5.

5. **Commit and render, with `--setup-only` only.** Shell and folder as step 4.

   ```
   git add -A
   ```

   ```
   git commit -m "Create the profile"
   ```

   The commit needs the identity from step 1; if it reports `unable to auto-detect email
   address`, go back and set it.

   Then render the profile into itself, and commit that render too. `--no-fetch` is needed
   because a new profile's remote may still be empty:

   ```
   python core/sync.py --profile . --self --write --no-fetch
   ```

   ```
   git add -A
   ```

   ```
   git commit -m "Render the profile"
   ```

6. **Push.** Shell and folder as step 4.

   ```
   git push -u origin main
   ```

   If the push gates ask for consent, answer as the prompt says.

7. **Delete the archive folder.** Shell: as above. Folder: `scratch`'s parent. From here
   on everything runs from `core/`.

   ```
   rm -rf scratch
   ```

   Replace `scratch` with yours. On PowerShell: `Remove-Item -Recurse -Force scratch`.

8. **Confirm.** Shell: as above. Folder: `work/acme-profile`.

   ```
   python core/toolboxctl.py version
   ```

   It prints `acme-owner/acme-core v0.1.19 <commit>`, with your values.

Update later with `python core/toolboxctl.py update`.
