# Code and Data Release for our preprint, _Clinician-Centered Evaluation of Large Language Model-Generated Discharge Summaries for Longer Hospitalizations: Insights from Hospitalists and Primary Care Physicians_

This repository serves as the public release of code and de-identified data used for the study. Individual README files are available within each submodule.

It is structured as follows:

* `code/eval_webapp/` -- exported version of the web application used to collect review data for this study. It has been slightly simplified for ease of use.
* `code/pipeline/` -- exported version of the LangChain/LangGraph pipeline used to generate the discharge summaries evaluated in this study. Original prompts are included. Fake data also included to allow proof-of-concept runs; OpenAI API key required. The code has been slightly simplified to allow for more generalized use.
* `data_and_results/data/` -- Deidentified raw data for likert scores and error annotations. Reviewer and patient identifiers have been completely removed. Incidental findings data was not able to be released due to HIPAA restrictions.
* `data_and_results/analysis` -- outputs of the `reproduce_results.py` script, corresponding to certain figures and tables in the manuscript and supplemental information.
