---
name: ginkgo-cloud-lab
description: "在 Ginkgo Bioworks Cloud Lab(cloud.ginkgo.bio) 上提交和管理协议，这是一个基于网络的网络界面，用于在可配置自动化卡茨(RACs)上进行自主的实验室执行.当用户想要运行蛋白质表达和纯化(无细胞，E.coli,或Pichia),HiBIT或A280或LabChip量化，IVT mRNA/circRNA合成，热移/可开发性测定，Echo-MS酶或解析方法，SPR目标登机，荧光像素艺术，或与Ginkgo Cloud Lab 服务互动时使用。"
license: MIT license
allowed-tools: Read
metadata:
  github_source: https://github.com/K-Dense-AI/scientific-agent-skills
  category: research_closed_loop
  trigger_keyword:
  - ginkgo-cloud-lab
  - ginkgo cloud lab
  - 投稿
  - submit
  - manage
  - protocols
  - ginkgo
  - bioworks
  - cloud
  - lab
  - bio
  - web-based
  prompt_mode: full
  enabled: 'true'
---
# Ginkgo Cloud Lab

## Overview

Ginkgo Cloud Lab (https://cloud.ginkgo.bio) provides remote access to Ginkgo Bioworks' autonomous lab infrastructure. Protocols are executed on Reconfigurable Automation Carts (RACs) -- modular units with robotic arms, maglev sample transport, and industrial-grade software spanning 70+ instruments.

The platform also includes **EstiMate**, an AI agent that accepts human-language protocol descriptions and returns feasibility assessments and pricing for custom workflows beyond the listed protocols.

The catalog is organized into **Expression & Purification** (in vitro / cell-free / E. coli / Pichia), **Characterization & Assay**, **Method & Target Onboarding**, and **Specialty**. Pick a protocol below, then read its reference file for inputs, outputs, the automated workflow, and ordering details.

## Available Protocols

### Expression & Purification - In vitro

| Protocol | Readout | Price | Turnaround | Status |
|---|---|---|---|---|
| [IVT mRNA/circRNA Synthesis](references/ivt-rna-synthesis-qpcr.md) | qPCR (mRNA or circRNA, 384-well) | $99/sample | up to 12 business days | Certified |

### Expression & Purification - Cell-free (E. coli CFPS)

| Protocol | Readout | Price | Turnaround | Status |
|---|---|---|---|---|
| [Validate sequence expression](references/cell-free-protein-expression-validation.md) | Go/no-go titer + purity (up to 1800 bp) | $39/sample | up to 10 days | Certified |
| [Optimize expression conditions](references/cell-free-protein-expression-optimization.md) | DoE across 24 conditions | $199/sample | up to 11 days | Certified |
| [Express + quantify (HiBiT)](references/cell-free-protein-expression-hibit.md) | Luminescence, no purification | $39/sample | up to 11 days | Certified |
| [Express + purify (A280)](references/cfps-strep-tag-purification-a280.md) | Strep-tag, A280 yield | $149/sample | up to 11 days | Certified |
| [Express + purify minibinder](references/minibinder-strep-tag-a280.md) | Strep-tag, A280, LabChip | $149/sample | up to 11 days | Certified |
| [Express + purify (A280 + LabChip)](references/cfps-expression-purification-quantification.md) | Strep-tag, A280 + purity/size | $159/sample | up to 12 days | Certified |

### Expression & Purification - E. coli

| Protocol | Readout | Price | Turnaround | Status |
|---|---|---|---|---|
| [Express + quantify (HiBiT)](references/ecoli-protein-expression-hibit.md) | Luminescence (up to 384 constructs) | $79/sample | up to 3 weeks | Certified |
| [Express + purify (A280)](references/ecoli-protein-expression-histag-a280.md) | His-tag, A280 yield | $199/sample | up to 3 weeks | Certified |
| [Express + purify minibinder](references/ecoli-minibinder-expression-histag-a280.md) | His-tag, A280 yield | $199/sample | up to 3 weeks | Certified |
| [Express + purify (A280 + LabChip)](references/ecoli-expression-purification-quantification.md) | His-tag, A280 + purity/size | $209/sample | up to 3 weeks | Certified |

### Expression & Purification - Pichia

| Protocol | Readout | Price | Turnaround | Status |
|---|---|---|---|---|
| [Express + quantify (LabChip)](references/pichia-protein-expression-labchip.md) | Secreted protein, size/purity (up to 96) | $89/sample | up to 4 weeks | Certified (New) |

### Characterization & Assay

| Protocol | Readout | Price | Turnaround | Status |
|---|---|---|---|---|
| [Express + thermal shift](references/cfps-strep-purification-thermal-shift.md) | SYPRO Orange Tm (Tonset, TM1-3) | $159/sample | up to 12 days | Certified |
| [Detect enzymatic products (Echo-MS)](references/echo-ms-cfps-detection.md) | Substrate/product by Echo-MS | $44/sample | up to 13 days | Beta |

### Method & Target Onboarding

| Protocol | Readout | Price | Turnaround | Status |
|---|---|---|---|---|
| [Onboard Echo-MS method](references/echo-ms-method-onboarding.md) | Calibration curve, LOD/LOQ | $799/molecule | up to 3 weeks | Certified |
| [Onboard SPR target](references/spr-target-onboarding.md) | Validated SPR capture method | $1,399/target | up to 4 weeks | Beta |

### Specialty

| Protocol | Readout | Price | Turnaround | Status |
|---|---|---|---|---|
| [Generate fluorescent pixel art](references/fluorescent-pixel-art-generation.md) | UV photo, 7-color E. coli palette | $25/plate | up to 7 days | Beta |

**Coming soon:** Protein Expression and Binding Affinity Characterization (express + purify, then screen binding affinity against a target).

## Choosing a Protocol

- **Quick expressibility screen?** Cell-free HiBiT ($39) or Validate sequence expression ($39).
- **Need purified protein + yield?** A280 tiers (cell-free or E. coli); add LabChip for purity/size.
- **Difficult / membrane / disulfide / cofactor targets?** Cell-free Optimize (24-condition DoE).
- **Secreted or eukaryotic targets?** Pichia expression.
- **Screening de novo binders/minibinders?** Cell-free or E. coli minibinder tiers, then SPR onboarding for kinetics.
- **Enzyme activity / biocatalysis?** Echo-MS enzymatic detection (onboard the analyte method first).
- **Stability / developability ranking?** Thermal shift assay.
- **RNA (mRNA/circRNA)?** IVT synthesis + qPCR.

## General Ordering Workflow

1. Select a protocol at https://cloud.ginkgo.bio/protocols
2. Configure parameters (number of proteins/samples/molecules/targets, replicates, plates)
3. Download the protocol's input template and upload inputs (FASTA/CSV/XLSX for sequence protocols; Design Tool for pixel art; vendor catalog numbers for onboarding)
4. Add any special requirements in the Additional Details field
5. Provide an email, agree to the protocol terms, and add to cart / submit to receive a feasibility report and price quote

For protocols not listed above, use the **EstiMate** chat (https://cloud.ginkgo.bio/estimate) to describe a custom protocol in plain language and receive a compatibility assessment and pricing.

## Authentication

Access Ginkgo Cloud Lab at https://cloud.ginkgo.bio. Account creation or institutional access may be required. Contact Ginkgo at cloud@ginkgo.bio for access questions.

## Key Infrastructure

- **RACs (Reconfigurable Automation Carts):** Modular robotic units with high-precision arms and maglev transport
- **Catalyst Software:** Protocol orchestration, scheduling, parameterization, and real-time monitoring
- **70+ integrated instruments:** Agilent Bravo liquid handlers, Beckman/Labcyte Echo acoustic dispensers, BMG PHERAstar / Tecan Spark readers, Revvity LabChip, Bio-Rad CFX Opus, Nicoya Alto SPR, SciEx Echo-MS, Inheco/Cytomat incubators, and more
- **Nebula:** Ginkgo's autonomous lab facility in Boston, MA
