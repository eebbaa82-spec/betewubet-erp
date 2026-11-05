# Putting the ERP on cPanel hosting

This puts the ERP at `https://www.eruditeafrica.net/Betewubet/`, next to the existing website,
using cPanel's **Setup Python App** and a MySQL (MariaDB) database. It takes about 20 minutes.

**You need:** cPanel with *Setup Python App* offering Python 3.10 or newer, *MySQL Databases*,
and *File Manager*. *Terminal* helps but is not required. The site should have HTTPS (cPanel AutoSSL).

## 1. Build the upload file (developer)

```
scripts/make-cpanel-bundle.sh /Betewubet www.eruditeafrica.net
```

This makes `dist-cpanel/betewubet-erp-cpanel.zip`: the backend, the web app already built for
`/Betewubet`, and a `site.env` settings file with a fresh secret key.

## 2. Create the database

cPanel > **MySQL Databases** (newer cPanel: **Database Wizard**, not the PostgreSQL one):

1. Create a database, e.g. `betewubet`. cPanel adds your account name in front, e.g. `erudite_betewubet`.
2. Create a user, e.g. `betewubet`, with a long password made of **letters and numbers only**.
3. Add the user to the database and tick **All Privileges**.

## 3. Upload the files

cPanel > **File Manager**, in your home folder (**not** inside `public_html`):

1. Upload `betewubet-erp-cpanel.zip`, then right-click it > **Extract**. You get a folder `betewubet-erp`.
2. Open `betewubet-erp/site.env` (right-click > Edit) and change the `DATABASE_URL` line, using the
   full names from step 2:
   `DATABASE_URL=mysql://erudite_betewubet:YourPassword@localhost:3306/erudite_betewubet`

## 4. Create the Python app

cPanel > **Setup Python App** > **Create Application**:

| Field | Value |
|---|---|
| Python version | the newest offered, at least 3.10 |
| Application root | `betewubet-erp/backend` |
| Application URL | `www.eruditeafrica.net` / `Betewubet` |
| Application startup file | `app_wsgi.py` (not `passenger_wsgi.py`) |
| Application Entry point | `application` |

Click **Create**. Then, on the same page:

1. Under *Configuration files*, add `requirements.txt` and click **Run Pip Install**.
2. Under *Execute python script*, enter `cpanel_setup.py` and click **Run Script**. It creates the
   tables, puts the web app's files in place and creates the `admin` user. **Copy the password it
   shows**; it is also saved in `betewubet-erp/backend/FIRST_LOGIN.txt`.
3. Click **Restart**.

No *Execute python script* box? Use cPanel > **Terminal**: copy the "Enter to the virtual
environment" command shown at the top of the app page, paste it, then run
`cd ~/betewubet-erp/backend && python cpanel_setup.py`.

To load the made-up sample month for a demonstration, run `cpanel_setup.py --sample`
instead (only on an empty database). For an empty system with just the sample products and
materials, use `--master-data`.

## 5. Open it

Go to `https://www.eruditeafrica.net/Betewubet/` and sign in as `admin`. Change the password in
**Back office > Users**, and add a user for each member of staff there.

## Updating to a new version

1. Build a new zip (step 1). Upload and extract it over the old folder, but **keep your
   `site.env`** (don't overwrite it with the new one).
2. In Setup Python App: **Run Pip Install**, run `cpanel_setup.py` again, then **Restart**.

## If something goes wrong

- **"Script exit code: 1"** after Run Script: scroll down in the output box under the button; the last
  lines under *stderr* say what failed.
- **500 page, and `stderr.log` ends in "RecursionError" with `load_source('wsgi', 'passenger_wsgi.py')`**:
  the startup file was set to `passenger_wsgi.py`. Set *Application startup file* to `app_wsgi.py`,
  click **Save**, then **Restart**.
- **Error page or "Incomplete response"**: open `betewubet-erp/backend/stderr.log` in File Manager;
  the last lines say what failed.
- **"Access denied for user"**: the user was not added to the database (step 2.3), or the
  `DATABASE_URL` names or password don't match.
- **Page shows without styling or says the web app has not been built**: run `cpanel_setup.py` again
  and restart.
- **"Bad Request (400)"**: the address you used is not in `ALLOWED_HOSTS` in `site.env`.
- **Python 3.10 or newer is not offered**: ask the hosting company to enable it. If they can't, a
  small VPS (about US$6 a month) runs the included `docker-compose.yml` setup instead.
