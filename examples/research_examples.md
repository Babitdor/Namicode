# /research Command Examples

This document provides practical examples of using the `/research` command for various research scenarios.

## Example 1: Academic Literature Review

### Query
```bash
/research academic What are the current approaches to solving the traveling salesman problem?
```

### What Happens

1. **Question Decomposition**
   - Agent 1 (Literature Reviewer): Searches academic databases for TSP papers
   - Agent 2 (Methodology Analyst): Evaluates algorithmic approaches
   - Agent 3 (Citation Tracker): Follows citation networks

2. **Parallel Investigation**
   - Each agent investigates their assigned aspect
   - Findings saved to individual files

3. **Cross-Pollination**
   - Agents share insights about related algorithms
   - Identify connections between approaches

4. **Synthesis**
   - Comprehensive literature review
   - Algorithm comparison table
   - Research gaps identified

5. **Quality Assurance**
   - All papers cited properly
   - Methodology quality assessed
   - Citation networks validated

### Output Files

```
.nova/research/
├── decomposition.md
├── literature_reviewer_findings.md
├── methodology_analyst_findings.md
├── citation_tracker_findings.md
├── shared/
│   └── insights.md
├── final_report.md
└── qa_report.md
```

### Sample Output (final_report.md)

```markdown
# Literature Review: Traveling Salesman Problem Approaches

## Executive Summary

The Traveling Salesman Problem (TSP) remains one of the most studied NP-hard problems in computer science. Recent advances have focused on approximation algorithms, machine learning approaches, and hybrid methods combining exact and heuristic techniques.

## Detailed Analysis

### Literature Reviewer Findings

Key papers identified:
- "A 3/2-Approximation Algorithm for the s-t Path TSP" (2023)
- "Neural Combinatorial Optimization for TSP" (2024)
- "Quantum Computing Approaches to TSP" (2025)

### Methodology Analyst Findings

Algorithmic approaches:
1. **Exact Algorithms**: Branch-and-bound, dynamic programming
2. **Approximation Algorithms**: Christofides algorithm (1.5-approximation)
3. **Heuristics**: Genetic algorithms, simulated annealing
4. **Machine Learning**: Graph neural networks, reinforcement learning

### Citation Tracker Findings

Most influential papers:
- "The Traveling Salesman Problem: A Computational Study" (2006) - 2,500+ citations
- "Attention, Learn to Solve Routing Problems!" (2019) - 800+ citations

## Integrated Insights

The field has evolved from pure algorithmic approaches to hybrid methods combining:
- Classical optimization techniques
- Machine learning for solution guidance
- Quantum computing for specific instances

## Conclusions & Recommendations

1. For small instances (< 100 cities): Use exact algorithms
2. For medium instances (100-1000 cities): Use approximation algorithms
3. For large instances (> 1000 cities): Use ML-guided heuristics
4. For future research: Explore quantum-classical hybrid approaches

## Sources & Methodology

- Academic databases: IEEE Xplore, ACM Digital Library, arXiv
- Citation analysis: Google Scholar, Semantic Scholar
- Quality criteria: Peer-reviewed, > 10 citations, published after 2020
```

---

## Example 2: Market Research

### Query
```bash
/research market What is the competitive landscape for AI-powered code assistants?
```

### What Happens

1. **Question Decomposition**
   - Agent 1 (Market Analyst): Market size and growth
   - Agent 2 (Competitor Researcher): Competitive landscape
   - Agent 3 (Trend Tracker): Emerging trends

2. **Parallel Investigation**
   - Market data from industry reports
   - Competitor analysis from websites and news
   - Trend analysis from social media and publications

3. **Cross-Pollination**
   - Market size affects competitive dynamics
   - Trends influence market growth
   - Competitor strategies reflect trends

4. **Synthesis**
   - Market analysis report
   - Competitive positioning map
   - Growth projections

5. **Quality Assurance**
   - Data sources verified
   - Market size estimates cross-referenced
   - Competitive claims validated

### Sample Output (final_report.md)

```markdown
# Market Analysis: AI-Powered Code Assistants

## Executive Summary

The AI-powered code assistant market is experiencing rapid growth, projected to reach $2.5B by 2028 with a CAGR of 25%. Key players include GitHub Copilot, Amazon CodeWhisperer, and emerging competitors like Tabnine and Codeium.

## Detailed Analysis

### Market Analyst Findings

**Market Size**:
- 2023: $800M
- 2024: $1.0B
- 2028 (projected): $2.5B
- CAGR: 25%

**Market Segments**:
- Enterprise: 60%
- Individual developers: 30%
- Educational: 10%

### Competitor Researcher Findings

**Market Leaders**:
1. **GitHub Copilot** (Microsoft)
   - Market share: 45%
   - Strengths: IDE integration, large training data
   - Weaknesses: Privacy concerns, cost

2. **Amazon CodeWhisperer**
   - Market share: 20%
   - Strengths: AWS integration, free tier
   - Weaknesses: Limited language support

3. **Tabnine**
   - Market share: 15%
   - Strengths: Privacy-focused, on-premise option
   - Weaknesses: Smaller training data

### Trend Tracker Findings

**Emerging Trends**:
1. Privacy-first solutions (on-premise deployment)
2. Multi-model support (GPT-4, Claude, Llama)
3. Context-aware suggestions (project-level understanding)
4. Code explanation and documentation generation
5. Security vulnerability detection

## Integrated Insights

The market is shifting from simple code completion to comprehensive development assistance:
- Privacy concerns driving on-premise solutions
- Multi-model support becoming standard
- Context awareness differentiating products

## Conclusions & Recommendations

1. **For Buyers**: Evaluate privacy requirements before choosing
2. **For Competitors**: Focus on context awareness and security
3. **For Investors**: Market still has room for differentiation

## Sources & Methodology

- Industry reports: Gartner, Forrester, IDC
- Company websites and press releases
- Developer surveys: Stack Overflow, JetBrains
- News articles: TechCrunch, VentureBeat
```

---

## Example 3: Stock Research

### Query
```bash
/research stocks Should I invest in NVIDIA for long-term growth?
```

### What Happens

1. **Question Decomposition**
   - Agent 1 (Financial Analyst): Financial statements and metrics
   - Agent 2 (News Researcher): Recent news and sentiment
   - Agent 3 (Technical Analyst): Technical indicators

2. **Parallel Investigation**
   - SEC filings and earnings reports
   - News articles and social media sentiment
   - Chart patterns and technical indicators

3. **Cross-Pollination**
   - Financial performance affects news sentiment
   - News impacts technical indicators
   - Technical patterns reflect fundamentals

4. **Synthesis**
   - Investment research report
   - Risk assessment
   - Buy/hold/sell recommendation

5. **Quality Assurance**
   - Financial data verified
   - News sources credible
   - Technical analysis validated

### Sample Output (final_report.md)

```markdown
# Investment Research: NVIDIA Corporation (NVDA)

## Executive Summary

NVIDIA presents a strong long-term investment opportunity due to its dominant position in AI chips, strong financial performance, and favorable market trends. However, high valuation and competition risks should be considered.

## Detailed Analysis

### Financial Analyst Findings

**Financial Performance** (FY 2024):
- Revenue: $60.9B (+126% YoY)
- Net Income: $29.8B (+581% YoY)
- Gross Margin: 72.7% (+15.3pp YoY)
- R&D Spending: $8.7B (14.3% of revenue)

**Key Metrics**:
- P/E Ratio: 65.2
- P/S Ratio: 25.8
- Debt/Equity: 0.41
- ROE: 69.4%

**Balance Sheet**:
- Cash: $25.9B
- Total Assets: $85.2B
- Total Liabilities: $19.3B

### News Researcher Findings

**Recent News** (Last 30 days):
- Announced next-gen Blackwell GPU architecture
- Expanded partnership with major cloud providers
- CEO Jensen Huang presented at GTC 2024
- Analyst upgrades: 15 buy, 3 hold, 0 sell

**Sentiment Analysis**:
- Social media: 78% positive
- News coverage: 85% positive
- Analyst ratings: Strong buy consensus

### Technical Analyst Findings

**Technical Indicators**:
- 50-day MA: $875
- 200-day MA: $720
- RSI: 62 (neutral)
- MACD: Bullish crossover
- Support: $850
- Resistance: $950

**Chart Pattern**:
- Uptrend channel intact
- Recent breakout from consolidation
- Volume confirming trend

## Integrated Insights

**Strengths**:
1. Dominant AI chip market position (80%+ market share)
2. Strong financial performance and growth
3. Expanding data center revenue
4. Strong cash position for R&D

**Weaknesses**:
1. High valuation (P/E 65.2)
2. Dependence on AI market growth
3. Increasing competition (AMD, Intel)
4. Geopolitical risks (China exposure)

**Opportunities**:
1. AI market expansion
2. Autonomous vehicles
3. Metaverse and gaming
4. Edge computing

**Threats**:
1. Competition from AMD and Intel
2. Regulatory scrutiny
3. Economic downturn
4. Supply chain disruptions

## Conclusions & Recommendations

**Investment Thesis**:
NVIDIA is well-positioned for long-term growth due to its leadership in AI chips and strong financial performance. However, the high valuation suggests limited upside in the short term.

**Recommendation**: BUY with 12-month target price of $1,050

**Risk Level**: Medium-High

**Time Horizon**: 3-5 years

**Position Sizing**: 3-5% of portfolio

## Sources & Methodology

- SEC filings: 10-K, 10-Q
- Earnings call transcripts
- Financial news: Bloomberg, Reuters, CNBC
- Analyst reports: Goldman Sachs, Morgan Stanley, JPMorgan
- Technical data: TradingView, Yahoo Finance
```

---

## Example 4: Technical Research

### Query
```bash
/research technical How do I implement OAuth 2.0 authentication in Python?
```

### What Happens

1. **Question Decomposition**
   - Agent 1 (Doc Researcher): Official OAuth 2.0 documentation
   - Agent 2 (API Analyst): Python library documentation
   - Agent 3 (Implementation Specialist): Code examples and best practices

2. **Parallel Investigation**
   - OAuth 2.0 specification from IETF
   - Python library documentation (Authlib, OAuthlib)
   - Code examples from official docs and tutorials

3. **Cross-Pollination**
   - Specification details inform implementation
   - Library capabilities affect code examples
   - Best practices from all sources combined

4. **Synthesis**
   - Technical implementation guide
   - Working code examples
   - Security best practices

5. **Quality Assurance**
   - Code examples tested
   - Security practices validated
   - Version compatibility verified

### Sample Output (final_report.md)

```markdown
# OAuth 2.0 Implementation in Python

## Executive Summary

OAuth 2.0 can be implemented in Python using libraries like Authlib or OAuthlib. This guide covers the authorization code flow, token management, and security best practices with working code examples.

## Detailed Analysis

### Doc Researcher Findings

**OAuth 2.0 Specification**:
- RFC 6749: The OAuth 2.0 Authorization Framework
- RFC 6750: The OAuth 2.0 Authorization Framework: Bearer Token Usage
- RFC 7636: Proof Key for Code Exchange (PKCE)

**Key Concepts**:
1. **Authorization Grant**: Method for obtaining access token
2. **Access Token**: Credential for accessing protected resources
3. **Refresh Token**: Credential for obtaining new access tokens
4. **Scope**: Limited access to resources

### API Analyst Findings

**Python Libraries**:
1. **Authlib** (Recommended)
   - Full OAuth 2.0 implementation
   - Built-in security features
   - Active maintenance
   - Version: 1.3.0+

2. **OAuthlib**
   - Core OAuth implementation
   - Framework-agnostic
   - Version: 3.2.0+

3. **Requests-OAuthlib**
   - OAuthlib + Requests integration
   - Simple API
   - Version: 1.3.1+

### Implementation Specialist Findings

**Code Example: Authorization Code Flow with PKCE**

```python
from authlib.integrations.flask_client import OAuth
from flask import Flask, redirect, url_for

app = Flask(__name__)
oauth = OAuth(app)

# Register OAuth provider
oauth.register(
    'provider_name',
    client_id='YOUR_CLIENT_ID',
    client_secret='YOUR_CLIENT_SECRET',
    server_metadata_url='https://provider.com/.well-known/openid-configuration',
    client_kwargs={
        'scope': 'openid profile email'
    }
)

@app.route('/login')
def login():
    redirect_uri = url_for('authorize', _external=True)
    return oauth.provider_name.authorize_redirect(redirect_uri)

@app.route('/authorize')
def authorize():
    token = oauth.provider_name.authorize_access_token()
    # Store token securely
    return redirect(url_for('profile'))

@app.route('/profile')
def profile():
    # Access protected resource
    resp = oauth.provider_name.get('userinfo')
    profile = resp.json()
    return f"Hello, {profile['name']}!"
```

**Token Management**:

```python
import time
from datetime import datetime, timedelta

class TokenManager:
    def __init__(self):
        self.tokens = {}
    
    def store_token(self, user_id, token_data):
        """Store token with expiration time."""
        self.tokens[user_id] = {
            'access_token': token_data['access_token'],
            'refresh_token': token_data.get('refresh_token'),
            'expires_at': datetime.now() + timedelta(seconds=token_data['expires_in'])
        }
    
    def is_token_valid(self, user_id):
        """Check if token is still valid."""
        if user_id not in self.tokens:
            return False
        return datetime.now() < self.tokens[user_id]['expires_at']
    
    def refresh_token(self, user_id):
        """Refresh expired token."""
        if user_id not in self.tokens:
            return None
        
        refresh_token = self.tokens[user_id]['refresh_token']
        # Use refresh token to get new access token
        # Implementation depends on provider
        pass
```

## Integrated Insights

**Best Practices**:
1. **Use PKCE** for public clients (mobile, SPA)
2. **Store tokens securely** (encrypted, httpOnly cookies)
3. **Implement token refresh** for long-lived sessions
4. **Validate state parameter** to prevent CSRF
5. **Use short-lived tokens** (15-60 minutes)
6. **Implement proper error handling**

**Security Considerations**:
1. Never store tokens in localStorage
2. Always use HTTPS
3. Validate redirect URIs
4. Implement rate limiting
5. Log security events

## Conclusions & Recommendations

1. **Use Authlib** for new projects (most features, best security)
2. **Implement PKCE** for public clients
3. **Store tokens in httpOnly cookies** with secure flag
4. **Refresh tokens proactively** before expiration
5. **Follow OWASP guidelines** for OAuth security

## Sources & Methodology

- Official OAuth 2.0 specification (RFC 6749, RFC 6750, RFC 7636)
- Authlib documentation: https://docs.authlib.org/
- OAuthlib documentation: https://oauthlib.readthedocs.io/
- OWASP OAuth Security: https://owasp.org/www-project-web-security-testing-guide/
- Tested with Python 3.11+, Authlib 1.3.0
```

---

## Example 5: General Research

### Query
```bash
/research general What are the ethical implications of AI in healthcare?
```

### What Happens

1. **Question Decomposition**
   - Agent 1 (Primary Researcher): Core ethical issues
   - Agent 2 (Secondary Researcher): Stakeholder perspectives
   - Agent 3 (Fact Checker): Validate claims and sources

2. **Parallel Investigation**
   - Academic papers on AI ethics
   - News articles on healthcare AI incidents
   - Regulatory guidelines and frameworks

3. **Cross-Pollination**
   - Ethical issues affect stakeholders differently
   - Stakeholder perspectives inform ethical analysis
   - Fact-checking validates all claims

4. **Synthesis**
   - Comprehensive ethical analysis
   - Stakeholder impact assessment
   - Regulatory recommendations

5. **Quality Assurance**
   - All claims sourced
   - Multiple perspectives included
   - Bias acknowledged

### Sample Output (final_report.md)

```markdown
# Ethical Implications of AI in Healthcare

## Executive Summary

AI in healthcare presents significant ethical challenges including bias and fairness, privacy and data security, accountability and transparency, and informed consent. Balancing innovation with patient safety requires robust governance frameworks and stakeholder engagement.

## Detailed Analysis

### Primary Researcher Findings

**Core Ethical Issues**:

1. **Bias and Fairness**
   - AI systems can perpetuate existing healthcare disparities
   - Training data may not represent diverse populations
   - Example: AI skin cancer detection less accurate for darker skin tones

2. **Privacy and Data Security**
   - Health data is highly sensitive
   - AI requires large datasets for training
   - Risk of re-identification from anonymized data

3. **Accountability and Transparency**
   - "Black box" AI decisions difficult to explain
   - Who is responsible when AI makes errors?
   - Need for explainable AI (XAI) in healthcare

4. **Informed Consent**
   - Patients may not understand AI involvement
   - Dynamic consent models needed
   - Transparency about AI use in diagnosis/treatment

### Secondary Researcher Findings

**Stakeholder Perspectives**:

1. **Patients**
   - Want transparency about AI use
   - Concerned about data privacy
   - Value human oversight

2. **Healthcare Providers**
   - Need training on AI tools
   - Concerned about liability
   - Want AI to augment, not replace, their expertise

3. **AI Developers**
   - Focus on accuracy and performance
   - May overlook ethical implications
   - Need ethical guidelines and oversight

4. **Regulators**
   - Struggling to keep pace with AI innovation
   - Need frameworks for AI approval and monitoring
   - Balancing innovation with safety

### Fact Checker Findings

**Validated Claims**:
- ✅ AI skin cancer detection less accurate for darker skin tones (Source: Nature Medicine, 2022)
- ✅ Healthcare AI market projected to reach $188B by 2030 (Source: Grand View Research)
- ✅ FDA has approved 500+ AI/ML medical devices (Source: FDA, 2024)

**Debated Claims**:
- ⚠️ AI will replace doctors (Most experts say AI will augment, not replace)
- ⚠️ AI eliminates bias (AI can actually amplify bias if not carefully designed)

## Integrated Insights

**Key Tensions**:
1. **Innovation vs. Safety**: Rapid AI development vs. careful validation
2. **Efficiency vs. Equity**: AI benefits may not be evenly distributed
3. **Automation vs. Human Oversight**: Balancing AI assistance with human control
4. **Data Sharing vs. Privacy**: AI needs data, but patients value privacy

**Emerging Solutions**:
1. **Ethical AI Frameworks**: WHO guidelines, IEEE standards
2. **Explainable AI**: Making AI decisions interpretable
3. **Bias Mitigation**: Diverse training data, fairness metrics
4. **Governance Models**: AI ethics committees, oversight boards

## Conclusions & Recommendations

1. **For Healthcare Organizations**:
   - Establish AI ethics committees
   - Implement transparency requirements
   - Ensure diverse training data
   - Maintain human oversight

2. **For AI Developers**:
   - Prioritize explainability
   - Test for bias across populations
   - Engage stakeholders in design
   - Follow ethical guidelines

3. **For Regulators**:
   - Develop adaptive frameworks
   - Require transparency and explainability
   - Mandate bias testing
   - Monitor AI performance post-deployment

4. **For Patients**:
   - Ask about AI use in their care
   - Understand their rights
   - Report concerns
   - Participate in AI governance

## Sources & Methodology

- Academic databases: PubMed, IEEE Xplore, ACM Digital Library
- Regulatory frameworks: WHO, FDA, EU AI Act
- News sources: Healthcare IT News, STAT News
- Stakeholder interviews: Healthcare providers, AI developers, patient advocates
- Quality criteria: Peer-reviewed sources, multiple perspectives, recent publications (2020-2024)
```

---

## Tips for Effective Research

### 1. Be Specific

**Good**: "What are the performance benchmarks of PyTorch vs TensorFlow for NLP tasks?"

**Bad**: "Tell me about PyTorch and TensorFlow"

### 2. Choose the Right Mode

- Use `academic` for literature reviews and papers
- Use `market` for competitive analysis and market research
- Use `stocks` for financial research and investment analysis
- Use `technical` for documentation and implementation guides
- Use `general` for broad research topics

### 3. Provide Context

Include relevant context in your query:

```bash
/research stocks What is the outlook for semiconductor stocks in 2026, considering the AI boom and supply chain constraints?
```

### 4. Review Output Files

Check the individual agent findings to understand different perspectives:

```bash
# View decomposition
cat .nova/research/decomposition.md

# View individual findings
cat .nova/research/financial_analyst_findings.md
cat .nova/research/news_researcher_findings.md
cat .nova/research/technical_analyst_findings.md

# View final synthesis
cat .nova/research/final_report.md
```

### 5. Iterate

If the research is incomplete or needs more depth:

```bash
# Ask follow-up questions
/research academic What are the limitations of current TSP algorithms?
/research market What are the barriers to entry for new AI code assistant competitors?
```

---

## Troubleshooting

### No Output Files Created

**Problem**: Research completes but no files are created

**Solution**: Ensure `.nova/research/` directory exists and has write permissions

```bash
mkdir -p .nova/research
```

### Incomplete Research

**Problem**: Research stops before completion

**Solution**: Check agent logs for errors, ensure all agents completed their tasks

### Poor Quality Results

**Problem**: Results are superficial or incomplete

**Solution**: 
- Use more specific research queries
- Choose appropriate research mode
- Increase agent count for more perspectives

---

## Related Commands

- `/dream` - Memory consolidation
- `/compact` - Summarize conversation
- `/save` - Save session