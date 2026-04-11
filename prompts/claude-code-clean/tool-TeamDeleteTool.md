# Team Delete Tool

Remove team and task directories when swarm work is complete.

## When to Use

After all teammates have finished their work and you want to clean up team resources.

## Important

TeamDelete will fail if the team still has active members. Gracefully terminate teammates first, then call TeamDelete after all teammates have shut down.

## What It Does

- Removes the team directory
- Removes the task directory
- Clears team context from the current session
