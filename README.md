# PaprikaRecipes

Automated recipe sync pipeline: Claude generates recipes as JSON, pushes them to this repo, and a GitHub Action uploads them to Paprika Recipe Manager.

## How It Works

1. A recipe `.json` file is pushed to `recipes/`
2. GitHub Action triggers, runs `sync_to_paprika.py`
3. Script authenticates with Paprika (v1 login, v2 sync)
4. Recipe is uploaded via the Paprika sync API
5. File is moved to `recipes/synced/` for history

## Recipe JSON Format

```json
{
  "name": "Recipe Name",
  "ingredients": "1 cup flour\n2 eggs\n1 tsp salt",
  "directions": "Step 1: Mix dry ingredients.\nStep 2: Add eggs.\nStep 3: Bake at 350F for 25 min.",
  "servings": "4",
  "prep_time": "10 min",
  "cook_time": "25 min",
  "source": "Claude",
  "notes": "Optional notes here",
  "categories": [],
  "rating": 0
}
```

Ingredients and directions use `\n` for line breaks.

## Credentials

Stored as GitHub repo secrets: `PAPRIKA_EMAIL` and `PAPRIKA_PASSWORD`.
