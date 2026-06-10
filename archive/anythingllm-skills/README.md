# AnythingLLM Custom Agent Skills

Custom skills for the Finance workspace agent. These give the AI agent the ability to
query real financial data from Postgres via n8n webhooks.

## Skills

| Skill | What it does | Triggered by |
|-------|-------------|--------------|
| **Get Transactions** | Fetches all transactions for a date range | "show me my transactions", "what did I spend last month" |
| **Get Account Balances** | Returns all account balances + net worth | "what are my balances", "how much do I have", "net worth" |
| **Filter Transactions** | Searches by account, category, amount, description, house tag | "show me grocery spending", "Amazon purchases", "house expenses" |
| **Spending Summary** | Category/account breakdown with top purchases | "spending breakdown", "where is my money going", "budget overview" |
| **Ask Finance Anything** | NL→SQL catch-all via Haiku, handles any custom question | "recurring subscriptions", "month over month", "spent at Starbucks" |
| **Override Transaction Category** | Manually recategorize a transaction (writes to DB) | "that Walmart charge was groceries", "recategorize this as Coffee" |
| **Remember Fact** | Saves a durable fact to /knowledge/<topic>.md (Haiku-deduped) | "remember that Ally is my emergency fund", "save: I prefer maple over oak" |
| **Recall Fact** | Searches the knowledge base for previously-saved facts | "what did I say about Ally?", "remind me what tools I have" |

## Deployment

Skills live at `/home/michael/anythingllm-plugins/agent-skills/` on the host, bind-mounted
into the container at `/app/server/storage/plugins/agent-skills/`.

### To redeploy after editing:
```bash
cp -r /home/michael/KiroProject/anythingllm-skills/* /home/michael/anythingllm-plugins/agent-skills/
docker restart anythingllm
```

No sudo needed. If docker still requires sudo, add yourself to the docker group:
`sudo usermod -aG docker $USER && newgrp docker`.

## Activation

After deploying, you still need to **enable** each skill in AnythingLLM:
1. Go to Workspace Settings → Agent Configuration → Skills
2. Toggle ON each custom skill
3. Save

## Architecture

```
User question → AnythingLLM Agent → Custom Skill (handler.js)
                                         ↓
                                    HTTP fetch to n8n webhook
                                         ↓
                                    n8n queries Postgres
                                         ↓
                                    Clean JSON returned to agent
                                         ↓
                                    Agent formats natural language response
```

The key design principle: skills return **plain JSON strings** only. Never return
raw response objects or anything that could contain circular references.
