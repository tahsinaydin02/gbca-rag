# Quick set review — section chunks, llama-3.3-70b-versatile


Gold paragraph retrieved for 3/8 answerable questions.


## q1 (factual)

**Q:** Which GBCAs did the ACR classify as Group I agents associated with nephrogenic systemic fibrosis?

**Expected:** Gadodiamide, gadopentetate and gadoversetamide — first-generation simple linear agents, no longer on the market.

**Gold paragraphs:** ['PMC12746363#p3']

**Retrieved gold:** ['PMC12746363#p3']

**Retrieved from:** ['PMC11870253', 'PMC12454587', 'PMC12746363', 'PMC3492017', 'PMC4468111', 'PMC7156386', 'PMC7853837']

**Answer:**

According to [PMC12746363], the American College of Radiology (ACR) classified first generation, simple linear Group I agents, including gadodiamide, gadopentetate, and gadoversetamide, as being associated with nephrogenic systemic fibrosis (NSF). However, [PMC12454587] also classifies Group I (Highest Risk) as containing linear agents, such as gadodiamide and gadopentetate dimeglumine, which is consistent with [PMC12746363].

`7 chunks, 1842 ctx tokens, 0.797s`


## q2 (numeric)

**Q:** What odds ratio of developing NSF after gadolinium exposure in advanced CKD was reported by a meta-analysis of six retrospective studies?

**Expected:** 26.7, with a 95% CI of 10.27-69.24.

**Gold paragraphs:** ['PMC3501952#p4']

**Retrieved gold:** NONE

**Retrieved from:** ['PMC3501952', 'PMC4468111', 'PMC5525362', 'PMC8001337']

**Answer:**

NOT ANSWERABLE FROM THE PROVIDED PASSAGES.

`6 chunks, 1637 ctx tokens, 0.43s`


## q3 (numeric)

**Q:** What eGFR threshold has been used to exclude patients from receiving gadolinium-based contrast?

**Expected:** eGFR below 30 mL/min/1.73 m2 counts as severe renal impairment and was an exclusion criterion; another study required eGFR above 30 for eligibility.

**Gold paragraphs:** ['PMC11403782#p8', 'PMC11642361#p8']

**Retrieved gold:** NONE

**Retrieved from:** ['PMC11870253', 'PMC12810539', 'PMC3305456', 'PMC4501068']

**Answer:**

One in five centers (9/45, 20%) do not currently offer contrast-enhanced CMR to patients with an eGFR <30 mL/min/1.73 m^2 [PMC11870253].

`7 chunks, 1979 ctx tokens, 0.457s`


## q4 (multi_hop)

**Q:** At what dose was gadopiclenol found non-inferior to gadobutrol, and why can it be dosed lower?

**Expected:** Gadopiclenol at 0.05 mmol/kg was non-inferior to gadobutrol at 0.1 mmol/kg in the PICTURE trial; it can be dosed lower because its T1 relaxivity is much higher than other extracellular agents.

**Gold paragraphs:** ['PMC10480682#p17', 'PMC11051151#p11']

**Retrieved gold:** ['PMC11051151#p11']

**Retrieved from:** ['PMC10289941', 'PMC10480682', 'PMC11051151', 'PMC12081572', 'PMC7559862', 'PMC8119273', 'PMC8597020']

**Answer:**

Gadopiclenol was found to be non-inferior to gadobutrol at a dose of 0.05 mmol/kg [PMC12081572]. It can be dosed lower because it has a higher T1 relaxivity than other macrocyclic GBCAs, allowing for similar contrast enhancement at a 50% lower dose [PMC12081572]. Specifically, its hydration number of 2 enables two water nuclei to interact with the gadopiclenol-caged gadolinium ion, resulting in a 2-3 fold increase in relaxivity [PMC12081572].

`8 chunks, 1705 ctx tokens, 0.732s`


## q5 (numeric)

**Q:** How does the half-life of the residual excretion phase compare between linear and macrocyclic GBCAs?

**Expected:** About 25 hours for currently approved linear agents versus about 6 hours for a macrocyclic agent, roughly 5-8 times longer.

**Gold paragraphs:** ['PMC10957598#p34']

**Retrieved gold:** NONE

**Retrieved from:** ['PMC10791848', 'PMC10957598', 'PMC3409035', 'PMC4879157', 'PMC6441101', 'PMC7769977']

**Answer:**

According to [PMC10791848], the long-lasting excretion is faster for macrocyclic GBCA. However, [PMC10957598] states that residual excretion half-lives are in the order of 25 h, but does not provide a direct comparison between linear and macrocyclic GBCAs. [PMC7769977] mentions that macrocyclic agents stay intact and are continuously eliminated from the brain, whereas residual Gd from linear agents was found to be present in different molecular species, but does not provide specific half-life values for comparison. Therefore, based on the available information, it can be said that macrocyclic GBCAs have a faster long-lasting excretion phase, but exact half-life values for comparison are not provided [PMC10791848].

`7 chunks, 1924 ctx tokens, 9.931s`


## q6 (multi_hop)

**Q:** How did gadolinium retention rank across gadodiamide, gadopentetate, gadoterate and gadoteridol in rodent studies, and how does that ordering relate to chelate structure?

**Expected:** Gadodiamide showed the most retention, followed by gadopentetate, with gadoterate and gadoteridol roughly equal and lowest. The two lowest are macrocyclic; the two highest are linear, and macrocyclic agents release free gadolinium more slowly.

**Gold paragraphs:** ['PMC10287697#p1', 'PMC10287697#p3']

**Retrieved gold:** ['PMC10287697#p3']

**Retrieved from:** ['PMC10287697', 'PMC4879157', 'PMC8837552']

**Answer:**

According to [PMC10287697], Tweedle et al. showed that gadolinium presence in rats and mice ranked as follows: gadodiamide (linear, non-ionic) > gadopentetate dimeglumine (linear, ionic) ≈ gadoterate meglumine (macrocyclic, ionic) ≈ gadoteridol (macrocyclic, ionic). This suggests that linear chelates, particularly the non-ionic linear agent gadodiamide, tend to have higher gadolinium retention than macrocyclic agents. [PMC8837552] also notes that linear agents typically have slightly higher levels of retention than macrocyclic agents.

`6 chunks, 1696 ctx tokens, 7.931s`


## q7 (factual)

**Q:** Are all linear gadolinium-based contrast agents in ACR Group I?

**Expected:** No. The substituted linear agents gadobenate and gadoxetate are Group II, together with the macrocyclic agents, and Group II has been associated with few if any NSF cases.

**Gold paragraphs:** ['PMC12746363#p3']

**Retrieved gold:** NONE

**Retrieved from:** ['PMC10289941', 'PMC11051151', 'PMC12454587', 'PMC3305456', 'PMC6420614', 'PMC9314041']

**Answer:**

According to [PMC12454587], Group I (Highest Risk) contains linear agents, such as gadodiamide and gadopentetate dimeglumine, but it does not explicitly state that all linear agents are in Group I. However, Group II (Intermediate Risk) also contains linear ionic agents, indicating that not all linear agents are in Group I [PMC12454587].

`7 chunks, 1774 ctx tokens, 13.808s`


## q8 (numeric)

**Q:** What is the T1 relaxivity in blood at 1.5 T of gadoxetate?

**Expected:** 7.3 l/mmol per second.

**Gold paragraphs:** ['PMC10957598#p36']

**Retrieved gold:** NONE

**Retrieved from:** ['PMC11051151', 'PMC13049235', 'PMC4688989', 'PMC5998550', 'PMC7464237', 'PMC8370648']

**Answer:**

NOT ANSWERABLE FROM THE PROVIDED PASSAGES.

`8 chunks, 1766 ctx tokens, 10.459s`


## q9 (unanswerable)

**Q:** What is the approved gadobutrol dose in mmol/kg for neonates under four weeks of age?

**Expected:** NOT ANSWERABLE FROM THE PROVIDED PASSAGES

**Gold paragraphs:** — none, should abstain

**Retrieved gold:** NONE

**Retrieved from:** ['PMC12630068', 'PMC4569598', 'PMC4943967', 'PMC7559862']

**Answer:**

NOT ANSWERABLE FROM THE PROVIDED PASSAGES.

`8 chunks, 1705 ctx tokens, 9.683s`


## q10 (unanswerable)

**Q:** What is the list price of a single vial of gadoterate meglumine in Europe?

**Expected:** NOT ANSWERABLE FROM THE PROVIDED PASSAGES

**Gold paragraphs:** — none, should abstain

**Retrieved gold:** NONE

**Retrieved from:** ['PMC4043962', 'PMC8056663', 'PMC8572637', 'PMC8597020', 'PMC8660719', 'PMC8837552']

**Answer:**

NOT ANSWERABLE FROM THE PROVIDED PASSAGES.

`7 chunks, 1834 ctx tokens, 10.571s`
