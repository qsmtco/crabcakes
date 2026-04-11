#!/bin/bash
# Bulk cleanup script for making prompts platform-agnostic
cd /home/q/projects/crabcakes/prompts/claude-code-clean/

# Global replacements across all .md files
for f in *.md; do
  # 1. Remove proprietary references
  sed -i \
    -e "s/Claude Code itself/this tool/g" \
    -e "s/Claude Code/this agent/g" \
    -e "s/Anthropic's official CLI for Claude //" \
    -e "s/Anthropic's official CLI//" \
    -e "s/Anthropic//" \
    -e "s/code\.claude\.com//g" \
    -e "s/~\/.claude\.json/~\/.config\/agent\/settings.json/g" \
    -e 's|an anthropics/claude-code#100 format|an owner/repo#number format (e.g. org/project#123)|g' \
    -e 's|anthropics/claude-code#100|org/project#123|g' \
    -e 's|ccshare links|session sharing links|g' \
    -e 's|ccshare|session sharing|g' \
    "$f"
  
  # 2. Generalize slash commands
  sed -i \
    -e 's|/issue|/feedback|g' \
    -e 's|/share|session sharing|g' \
    "$f"
  
  # 3. Clean template variable artifacts - [variable] patterns
  sed -i \
    -e 's/\[globalSettings\.join.*\]//' \
    -e 's/\[projectSettings\.join.*\]//' \
    -e 's/\[modelSection\]//' \
    -e 's/\[functionName()\]//g' \
    -e 's/\[VARIABLE\]//g' \
    "$f"
  
  # 4. Clean ${variable} artifacts  
  sed -i \
    -e 's/\${BRIEF_PROACTIVE_SECTION.*}//' \
    -e 's/\${commitAttribution.*}/MARKER_COMMIT_ATTR/' \
    -e 's/\${prAttribution.*}/MARKER_PR_ATTR/' \
    "$f"
  
  # 5. Convert unicode escapes
  sed -i 's/\\u2014/—/g' "$f"
  
  # 6. Remove Slack channel references
  sed -i '/#claude-code-feedback/d' "$f"
  sed -i '/C07VBSHV7EV/d' "$f"
  
  # 7. Model name generalizations
  sed -i \
    -e 's/"model", "value": "opus"/"model", "value": "your-preferred-model"/' \
    -e 's/model: opus/model: your-preferred-model/' \
    "$f"
  
  # 8. FILE_EDIT_TOOL_NAME cleanup
  sed -i 's/\[FILE_EDIT_TOOL_NAME\]/the file edit tool/g' "$f"
  
  echo "Processed: $f"
done

echo "Done!"
