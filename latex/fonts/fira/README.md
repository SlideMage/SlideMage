# Fira fonts for the "fira" layout profile

The seven files SlideMage_layout_fira.tex loads: Fira Sans Light, Light Italic, Regular and Italic (text) and Fira
Mono Regular, Medium and Bold (code). They are a fallback: the layout uses the TeX distribution's Fira (the `fira`
package of CTAN, in MiKTeX and TeX Live) when it has one, and these files only when it has none, so a TeX
installation without the large font collections (Debian's and Ubuntu's texlive-fonts-extra) still typesets in Fira.

| Family | Version | Source | License |
|---|---|---|---|
| Fira Sans | 4.301 | CTAN `fira` (fonts/opentype/public/fira), as installed by MiKTeX | SIL Open Font License 1.1 (`LICENSE-Fira-OFL.txt`) |
| Fira Mono | 3.201 | the same | the same |
