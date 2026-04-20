# Git Workflow Cheat Sheet

This is a quick reference for common Git commands and workflow steps for this project.

---

## ✅ Start New Work
git checkout main  
git pull origin main  
git checkout -b feature/my-change  

---

## 💾 Save Progress (Commit)
git add .  
git commit -m "Describe what I changed"  

---

## 🚀 Push Branch to GitHub
git push -u origin feature/my-change  

---

## 🔀 Open Pull Request
1. Go to the repo on GitHub.  
2. Click **"Compare & pull request"**.  
3. Describe your changes and submit the PR.  

---

## 📥 Merge to Main After Approval
git checkout main  
git pull origin main  

---

## 🧹 Cleanup Old Branches (Optional)
# Delete local branch  
git branch -d feature/my-change  

# Delete remote branch  
git push origin --delete feature/my-change  

---

## 🕵️ Useful Log Commands
git log --oneline     # compact history  
git status            # what changed since last commit  

---

💡 **Tip:** Always pull `main` before starting new work to avoid conflicts.
