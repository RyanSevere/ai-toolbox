#!/bin/sh
################################################################################
# File: dead-variants.sh
# Path: {PROJECT_ROOT}/githooks/gates/dead-variants.sh
# Created by: Ryan Severe
# Created: 2026-09-23
# Last Updated: 2026-11-16
# Description: Refuses a tracked file whose name ends in a dead-variant suffix.
#              Ported from workflows/dead-variants.yml so it runs before a push
#              rather than after one. Exit 0 passes, non-zero fails, and
#              everything printed becomes the detail in the gate report.
################################################################################
# ===========================================================================
#
#
#            "~,
#                *m,
#                   *9m;
#                       *%pg
#                          "YRWu
#                              *9$&w
#                                  *R$&w
#   ;j]@@W;                   *w,      79&&w;
#   :|*%MT"                     7&&w,      ?78BWw
# . ,|*       -p     ~            *R$$$gw,     '*MU@m,
#            =W/?*%NMWgw             *T&$F ,@w;     "*4[%m,
#              7R$$$$$$$$g          yg$$Gg$@@Hh!j ,w     "*w|j=,
#       ..     ]K@ww[T$Fff            >*MB&&@@Hh ]hk{!!~^     "*v'
#          '|;, *M@@&&$P                 $$&@HHH\  ` ;w,,   ,~""
#            "|jj]]%@F"                  ]$@@H, ;*M%P)a$$C  c
#           . :|j[M"                     ]@@HHr TfR4&$NE*,/~<'
#             `!||j]@@@A`                ]@@Hh~ *TT"" "* ^ r  '~
#                *ojKM"                  l@Hh~  "*|"'   /        `
#                                        @HHkC ,;!"
#                                       ]HHhr/|!"'
#                                       #Hhr!||"
#                             ,@r       hkr!||'
#                                      [k{|!"
#                                     (r!!"        r
#                                     !!"        r
#                                      ";      /
#                                             '
#                                            '
# ===========================================================================


set -eu

# The discriminator is the TRAILING segment, not the presence of a word and not
# the number of dots. Two looser patterns were tried and rejected, both
# measured on real repositories:
#
#   'backup' anywhere   -> 11 false positives. backup_to_remote.sh, clean_backup.sh,
#                          remote_backup.env.example. Backing things up is a feature.
#   doubled extension   -> 10 false positives. tsconfig.node.json,
#                          postcss.config.cjs, app.conf.template.
#
# This one matched 12 files across seven repositories with no false positive.
pattern='\.(backup|bak|old|orig|save|archive|copy|tmp|deprecated|unused|broken|prev)([.-][A-Za-z0-9._-]*)?$'

# Tracked files only. An untracked stray is nobody else's problem, and it also
# keeps "the gate is green" and "there are no stray backups" as separate
# statements. They are.
dead="$(git ls-files | grep -Ei "$pattern" || true)"

if [ -z "$dead" ]; then
  echo "No dead-variant filenames."
  exit 0
fi

printf '%s\n' "$dead" | sed 's/^/  /'
echo ""
echo "A file kept as a variant of another is read, grepped and occasionally"
echo "edited in place of the live one. Version control already holds every"
echo "previous version of anything tracked, so the copy buys nothing and costs"
echo "a wrong edit."
echo ""
echo "Delete them. If one is genuinely load-bearing, rename it to say what it"
echo "is rather than what it used to be."
exit 1
