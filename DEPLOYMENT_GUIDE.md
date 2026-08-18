# Institute Management System - Render.com Deployment Guide

This guide will help you deploy your Institute Management System to Render.com's free tier. No technical expertise required - just follow these simple steps!

## What is Render.com?

Render.com is a cloud platform that lets you host websites and applications for free. It's perfect for small projects like this institute management system.

## Prerequisites (What you need before starting)

1. **A GitHub account** (free at github.com)
2. **Your project files** on your computer
3. **About 30 minutes** of your time
4. **A credit card** (for Render verification only - you won't be charged on free tier)

---

## Step 1: Prepare Your Project Files

### 1.1 Check if you have these files in your project folder:

Make sure these files exist in your main project folder (d:/guha/institute/):
- `requirements.txt` (list of Python packages)
- `Procfile` (tells Render how to run your app)
- `.gitignore` (files to exclude from upload)
- `config.py` (configuration settings)
- `app/` folder (contains your application code)
- `run.py` (main application file)

**All these files should already be there from our setup.**

### 1.2 Create a .env file for secrets

Create a new file named `.env` in your project folder with these contents:

```
SECRET_KEY=your-secret-key-here-change-this
CRON_SECRET=your-cron-secret-here-change-this
FLASK_ENV=production
```

**Important:** Replace `your-secret-key-here-change-this` with a random string of letters and numbers. You can use something like: `my-institute-app-secret-key-2024`

---

## Step 2: Upload Your Code to GitHub

### 2.1 Create a GitHub account (if you don't have one)

1. Go to https://github.com
2. Click "Sign up"
3. Follow the instructions to create your free account
4. Verify your email address

### 2.2 Create a new repository on GitHub

1. After logging in to GitHub, click the **+** icon in the top-right corner
2. Select **"New repository"**
3. Fill in these details:
   - **Repository name**: `institute-management` (or any name you like)
   - **Description**: Institute Management System
   - **Public/Private**: Choose **Private** (recommended for security)
4. Click **"Create repository"**

### 2.3 Upload your project files

**Option A: Using GitHub Website (Easier for beginners)**

1. On your new repository page, click **"uploading an existing file"**
2. Drag and drop ALL your project files and folders into the upload area
3. Make sure to upload:
   - All `.py` files
   - The `app/` folder with all its contents
   - The `templates/` folder
   - The `static/` folder
   - `requirements.txt`
   - `Procfile`
   - `.gitignore`
   - `config.py`
   - `run.py`
4. Scroll down and click **"Commit changes"**
5. In the commit message box, type: "Initial upload"
6. Click **"Commit changes"**

**Option B: Using Git Command Line (If you're comfortable with commands)**

1. Open your project folder in terminal/command prompt
2. Run these commands one by one:

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/institute-management.git
git push -u origin main
```

Replace `YOUR_USERNAME` with your actual GitHub username.

---

## Step 3: Create a Render.com Account

### 3.1 Sign up for Render

1. Go to https://render.com
2. Click **"Sign Up"** in the top-right corner
3. Click **"Sign up with GitHub"** (easiest method)
4. Authorize Render to access your GitHub account
5. Fill in your details and create your Render account
6. **Important**: You'll need to add a credit card for verification (free tier won't charge you)

### 3.2 Verify your account

1. Render will send you a verification email
2. Click the link in the email to verify
3. Add your credit card details when prompted (this is just for verification)

---

## Step 4: Deploy Your Application

### 4.1 Create a new Web Service

1. After logging in to Render, click **"New +"** in the top-right corner
2. Select **"Web Service"**
3. Render will show your GitHub repositories
4. Find and select your `institute-management` repository
5. Click **"Connect"**

### 4.2 Configure your Web Service

Fill in these settings:

**Basic Settings:**
- **Name**: `institute-management` (or any name you prefer)
- **Region**: Choose the region closest to your users (e.g., Oregon for US, Frankfurt for Europe)
- **Branch**: `main`

**Build & Deploy Settings:**
- **Runtime**: `Python`
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `gunicorn -w 2 -b 0.0.0.0:$PORT wsgi:app`

**Environment Variables (Very Important!):**

Scroll down to "Environment Variables" section and add these:

1. Click **"Add Environment Variable"**
2. Add these variables one by one:

| Key | Value |
|-----|-------|
| `SECRET_KEY` | `your-secret-key-here-change-this-to-something-random` |
| `CRON_SECRET` | `your-cron-secret-here-change-this-to-something-random` |
| `FLASK_ENV` | `production` |

**Important:** Use the same secret keys you put in your `.env` file earlier.

### 4.3 Add a PostgreSQL Database (Free Tier)

1. Scroll down to the bottom of the page
2. Click **"Add Database"**
3. Select **"PostgreSQL"**
4. Choose the **Free** tier
5. Click **"Create Database"**

### 4.4 Connect Database to Your App

1. After the database is created, go back to your Web Service settings
2. Scroll to "Environment Variables"
3. You'll see a new variable automatically added: `DATABASE_URL`
4. This connects your app to the PostgreSQL database

### 4.5 Deploy!

1. Click **"Create Web Service"** at the bottom
2. Render will start building and deploying your app
3. This takes about 3-5 minutes
4. You can watch the progress in the "Logs" section

---

## Step 5: Initialize Your Database

After deployment, you need to set up your database with initial data.

### 5.1 Access your deployed app

1. Once deployment is complete, Render will give you a URL like: `https://institute-management.onrender.com`
2. Click this URL to open your app
3. You should see the login page

### 5.2 Create the first admin user

Since this is a fresh deployment, you need to create the first admin account:

1. Go to this URL in your browser: `https://institute-management.onrender.com/register`
   (Replace `institute-management` with your actual app name)
2. Fill in the registration form:
   - **Email**: Your email address
   - **Password**: Choose a strong password
   - **Name**: Your name
3. Click **"Register"**
4. Log in with your new account

### 5.3 Set up as Admin user

By default, new users are not admins. You need to make yourself an admin:

**Option A: Use Render Shell (Recommended)**

1. Go to your Render dashboard
2. Click on your Web Service
3. Click **"Shell"** tab
4. Type this command and press Enter:

```bash
python -c "from app import create_app; from app.models import User; app = create_app(); with app.app_context(): u = User.query.filter_by(email='YOUR_EMAIL').first(); u.role = 'Admin'; from app.extensions import db; db.session.commit(); print('User updated to Admin')"
```

Replace `YOUR_EMAIL` with your actual email address.

**Option B: Direct Database Access**

If the shell doesn't work, you can use Render's PostgreSQL dashboard:

1. Go to your PostgreSQL database in Render
2. Click **"External Connections"**
3. Use a database tool like TablePlus or DBeaver to connect
4. Run this SQL query:

```sql
UPDATE user SET role = 'Admin' WHERE email = 'YOUR_EMAIL';
```

Replace `YOUR_EMAIL` with your actual email address.

---

## Step 6: Set Up Automatic Backups (Optional but Recommended)

Render PostgreSQL free tier includes automatic backups, but you can set up additional backup cron jobs:

### 6.1 Create a Backup Script

1. Go to your Render dashboard
2. Click **"Cron Jobs"** → **"New Cron Job"**
3. Configure:
   - **Name**: `daily-backup`
   - **Schedule**: `0 2 * * *` (runs daily at 2 AM)
   - **Command**: `pg_dump $DATABASE_URL > /tmp/backup.sql`
4. Click **"Create Cron Job"**

---

## Step 7: Test Your Deployment

### 7.1 Check all features

1. Log in to your deployed app
2. Test these features:
   - Dashboard loads correctly
   - Can add students
   - Can add courses
   - Can mark attendance
   - Can record fees
   - Reports work

### 7.2 Check staff features

1. Create a tutor account
2. Link it to a staff user
3. Test staff login and verify:
   - Staff sees only their courses
   - Staff sees only their students
   - Staff can mark attendance
   - Staff can view reports
   - Staff cannot add/edit/delete (read-only)

---

## Step 8: Maintenance Tips

### 8.1 Monitor your app

- Regularly check Render dashboard for any errors
- Monitor resource usage (free tier has limits)
- Check logs for any issues

### 8.2 Update your app

When you make changes to your code:

1. Commit changes to GitHub
2. Render will automatically detect and redeploy
3. Wait for deployment to complete
4. Test the changes

### 8.3 Database backups

- Render automatically backs up PostgreSQL daily
- You can download manual backups from the Render dashboard
- Keep local backups of important data

---

## Troubleshooting Common Issues

### Issue 1: Deployment fails

**Solution:**
- Check the Render logs for error messages
- Make sure all files are uploaded to GitHub
- Verify environment variables are set correctly
- Check that `requirements.txt` includes all dependencies

### Issue 2: App loads but shows errors

**Solution:**
- Check the Render logs
- Make sure database is connected
- Verify SECRET_KEY is set
- Try redeploying from the Render dashboard

### Issue 3: Can't log in

**Solution:**
- Make sure you registered first
- Check if your user is set as Admin (use the shell command above)
- Clear your browser cache and try again

### Issue 4: Database connection errors

**Solution:**
- Verify DATABASE_URL environment variable is set
- Check that PostgreSQL database is running
- Try restarting the web service from Render dashboard

### Issue 5: Free tier limits reached

**Solution:**
- Render free tier has limits on resources
- If you exceed limits, consider upgrading to a paid plan
- Optimize your app to use fewer resources

---

## Important Notes

### Free Tier Limitations

Render's free tier includes:
- **512 MB RAM** (memory)
- **0.1 CPU** (processing power)
- **10 GB PostgreSQL storage**
- **Automatic SSL certificates**
- **Custom domains** (with some limitations)

### What to Monitor

- **Memory usage**: If consistently high, consider optimizing
- **Response time**: Should be under 3 seconds
- **Error rate**: Should be minimal
- **Database size**: Monitor growth

### When to Upgrade

Consider upgrading to paid tier if:
- You have many users (50+)
- App is slow frequently
- You need more storage
- You need better performance

---

## Security Best Practices

1. **Keep your SECRET_KEY secret** - never share it
2. **Use strong passwords** for all accounts
3. **Enable two-factor authentication** on GitHub and Render
4. **Regularly update dependencies** (check for security updates)
5. **Monitor access logs** for suspicious activity
6. **Keep backups** of important data

---

## Getting Help

If you run into issues:

1. **Render Documentation**: https://render.com/docs
2. **Render Community**: https://community.render.com
3. **GitHub Issues**: Check if others have similar problems
4. **Contact Support**: Render offers email support for paid plans

---

## Summary Checklist

Before deploying, make sure you have:
- [ ] All project files ready
- [ ] GitHub account created
- [ ] Code uploaded to GitHub
- [ ] Render account created
- [ ] Credit card added (for verification)
- [ ] Environment variables configured
- [ ] PostgreSQL database created
- [ ] App deployed successfully
- [ ] Admin user created
- [ ] All features tested
- [ ] Backup system set up

---

## Congratulations! 🎉

Your Institute Management System is now live on Render.com! You can access it from anywhere with an internet connection.

**Your app URL**: `https://your-app-name.onrender.com`

Share this URL with your staff and start using your system!

---

## Next Steps

1. **Add your staff users** - Create accounts for all your staff
2. **Import your data** - Add students, courses, and other data
3. **Train your staff** - Show them how to use the system
4. **Monitor performance** - Keep an eye on how the app performs
5. **Gather feedback** - Ask users for suggestions and improvements

---

**Last Updated**: July 2026
**For questions or issues**, refer to Render's documentation or community forums.
