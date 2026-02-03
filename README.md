# Frappe Repository Starter

A GitHub template repository that automatically initializes a new Frappe application when you create a repository from this template. The initialization workflow runs automatically and sets up your Frappe app with zero manual configuration.

## ✨ Features

- 🚀 **Automatic App Initialization** - Creates a Frappe app using `bench new-app` on repository creation or first push
- 🤖 **Bot-Powered** - Uses GitHub App for secure, automated operations
- 🔄 **Always Up-to-Date** - Uses latest Frappe boilerplate from `bench new-app`
- ⚡ **Zero Manual Setup** - Just create repo from template and the workflow handles everything
- 🔒 **Priority Execution** - Initialization workflow runs first and blocks other workflows until completion

## 🚀 Quick Start

### 1. Create New Repository

1. Click **"Use this template"** button above
2. Enter repository name (e.g., `student-portal`, `fee-management`)
3. Click **"Create repository"**

### 2. Wait for Initialization

The workflow automatically:
- Runs `bench new-app` with your app name (derived from repo name)
- Copies the generated app to repository root
- Commits and pushes the initialized app
- Deletes the initialization workflow file

⏱️ **Takes ~3-5 minutes**

> **Note:** The initialization workflow has priority and will block all other workflows until it completes successfully.

### 3. Check Progress

1. Go to **Actions** tab in your new repo
2. Watch the "Initialize Frappe App" workflow
3. Once complete, your app is ready!

## 📁 Generated Structure

After initialization, your repo will have:
```
your-repo/
├── app_name/                       # App module (from bench new-app)
│   ├── __init__.py
│   ├── hooks.py
│   ├── modules.txt
│   ├── patches.txt
│   ├── templates/
│   ├── public/
│   └── app_name/
│       └── __init__.py
├── pyproject.toml                  # Python project configuration
├── license.txt                     # MIT License
└── README.md                       # This file
```

The app name is automatically derived from your repository name (see naming convention below).

## 📝 Naming Convention

The app name is automatically derived from your repository name with the following rules:

| Repository Name | App Name | App Title |
|-----------------|----------|-----------|
| `frappe_hufdms` | `hufdms` | `Hufdms` |
| `frappe-hufdms` | `hufdms` | `Hufdms` |
| `frappe_student_portal` | `student_portal` | `Student Portal` |
| `student-portal` | `student_portal` | `Student Portal` |
| `fee-management` | `fee_management` | `Fee Management` |

**Rules:**
- Repository name is converted to `snake_case` for app name
- Hyphens (`-`) become underscores (`_`)
- **`frappe_` prefix is automatically removed** from the beginning
- All lowercase for app name
- Title Case for app title (after removing frappe prefix)

## 🔧 Using the Generated App

### Install in Your Bench
```bash
# Clone the app
bench get-app git@github.com:dhwani-ris/your-repo-name.git

# Install on site
bench --site yoursite.localhost install-app your_app_name

# Run migrations (if any)
bench --site yoursite.localhost migrate
```

### Development Workflow
```bash
# Create feature branch
git checkout -b feature/your-feature

# Make changes to your app...

# Commit your changes
git commit -m "feat: add new doctype for student records"

# Push and create PR
git push origin feature/your-feature
```

## ⚙️ Configuration

### App Details (Auto-Generated)

The workflow automatically sets these values when creating the app:

| Property | Value |
|----------|-------|
| **Publisher** | DHWANI RIS |
| **Email** | frappeteam@dhwaniris.com |
| **License** | MIT |
| **Frappe Branch** | develop |
| **Default Branch** | develop |

### Modify Defaults

To change default values, edit `.github/workflows/init-frappe-app.yml` before creating repositories:

```yaml
# In .github/workflows/init-frappe-app.yml

expect "App Publisher*"
send "Your Company Name\r"

expect "App Email*"
send "your-email@company.com\r"

expect "App License*"
send "mit\r"
```

## 🤖 GitHub App Setup

This template uses a GitHub App for authentication. If you're setting this up for a new organization:

### 1. Create GitHub App

1. Go to: `https://github.com/organizations/YOUR-ORG/settings/apps`
2. Click **"New GitHub App"**
3. Configure:
   - **Name:** `your-org-release-bot`
   - **Permissions:**
     - Contents: Read & Write
     - Metadata: Read-only
     - Workflows: Read & Write
   - **Installation:** Only on this account
4. Create and note the **App ID**
5. Generate **Private Key** (downloads `.pem` file)

### 2. Install App

1. Go to App settings → **Install App**
2. Install on your organization
3. Select **All repositories**

### 3. Add Secrets

Add these organization secrets:

| Secret Name | Value |
|-------------|-------|
| `DHWANI_RELEASE_BOT_APP_ID` | Your App ID |
| `DHWANI_RELEASE_BOT_PRIVATE_KEY` | Contents of `.pem` file |

## 🔍 Troubleshooting

### Workflow Not Running

**Check:**
- Is this a new repo created from template?
- Is this the first push to main/master?
- Does the app folder already exist? (skip condition)

### Permission Denied

**Check:**
- Is the GitHub App installed on the repo?
- Are organization secrets configured?
- Does the App have correct permissions?

### App Already Initialized

The workflow skips if an app folder already exists. To re-initialize:

1. Delete the app folder manually
2. Re-run the workflow from Actions tab

## 📚 Related Resources

- [Frappe Framework Documentation](https://frappeframework.com/docs)
- [Frappe Bench Documentation](https://github.com/frappe/bench)
- [Conventional Commits](https://www.conventionalcommits.org/)
- [Semantic Release](https://semantic-release.gitbook.io/)

## 🤝 Contributing

1. Fork the repository
2. Create feature branch: `git checkout -b feature/improvement`
3. Commit changes: `git commit -m "feat: add new feature"`
4. Push: `git push origin feature/improvement`
5. Open Pull Request

## 📄 License

MIT License - see [LICENSE](license.txt) for details.

---

**Maintained by DHWANI RIS Frappe Team** | frappeteam@dhwaniris.com
