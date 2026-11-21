# DocForge Inno Setup AppId fix

Apply to the repository root, replacing the existing `windows/inno/DocForge.iss`.

```bash
unzip -o ~/Downloads/DocForge-Inno-AppId-Fix-1.11.8.zip -d ~/Projects_/DocForge
cd ~/Projects_/DocForge
git add windows/inno/DocForge.iss
git commit -m "fix: escape Inno Setup AppId GUID"
git push origin main
```

The original application identifier is preserved. Only Inno Setup escaping changes.
