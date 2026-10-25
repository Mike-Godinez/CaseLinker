# Paired sample judgments

200 case ids in `phase3_paired_sample_ids.txt`, seed 20261017.
A stored final is a real wrong only when the passage does not support it as that field.
The passage check can reject a supported final; those rows are false flags and are not in the Results wrong column.

## Fixed before the table

`doj_safe_childhood_2023_259` stored victim age 9 from "whom he believed was the father of a nine-year-old boy" followed by an undercover officer. That is a persona, not a victim. The age readers now mark that pattern as a decoy. The case was re-read from its stored text and re-resolved. Victim ages on that case are empty. Perpetrator age 27 and the imposed sentence were left in place.

## Passage-check rejections still stored

### v2

- `doj_ceos_2013_032` sentence imposed `mandatory minimum` — real_wrong
  - verview) pleaded guilty today to production of child pornography. Meyer faces a mandatory minimum of 15 years, up to a maximum of 30 years in federal prison. According to court
- `doj_ceos_2013_032` sentence imposed `15 years` — real_wrong
  - ty today to production of child pornography. Meyer faces a mandatory minimum of 15 years, up to a maximum of 30 years in federal prison. According to court documents, Meyer is a member of the Unite
- `doj_ceos_2013_032` sentence imposed `30 years` — real_wrong
  - ld pornography. Meyer faces a mandatory minimum of 15 years, up to a maximum of 30 years in federal prison. According to court documents, Meyer is a member of the Unite
- `doj_ceos_2025_038` sentence imposed `15 years` — real_wrong
  - 026. Due to his prior conviction, Gonzalez faces a mandatory minimum penalty of 15 years in prison and a maximum penalty of 40 years in prison. A federal district court
- `doj_ceos_2013_138` age victims `15` — false_flag
  - Parkville Woman Sentenced To 15 Years In Prison For Conspiring To Produce Child Pornography September 03, 2013 Publication date
- `doj_safe_childhood_2024_251` age perpetrators `30` — false_flag
  - date: 2024-07-10 Source: AUGUSTA, GA: A Columbia County man has been sentenced to nearly 30 years in federal prison after pleading guilty to producing images of child sexual exploitation.
- `doj_safe_childhood_2026_253` sentence imposed `20 years` — real_wrong
  - an overseas server to access and store child pornography. Campbell faces up to 20 years’ imprisonment on each count, and a lifetime of supervision upon release. Senten
- `doj_safe_childhood_2026_121` sentence imposed `40 years` — real_wrong
  - regard for the law and a disturbing willingness to reoffend. He now faces up to 40 years in federal prison. My office, working alongside our partners at the FBI and oth
- `doj_safe_childhood_2025_397` sentence imposed `supervised release` — real_wrong
  - n, 23, was sentenced to five years in federal prison, followed by five years of supervised release, and ordered to pay a $100 special assessment to the Federal Crime Victims Fund
- `doj_safe_childhood_2023_525` sentence imposed `20 years` — real_wrong
  - the United States Marshal pending sentencing. Urelius faces a sentence of up to 20 years imprisonment without the possibility of parole, a fine of not more than $250,00
- `doj_safe_childhood_2025_278` sentence imposed `supervised release` — real_wrong
  - g his term of imprisonment, Carter will be required to serve a ten-year term of supervised release. There is no parole in the federal system. United States Attorney Richard D. We
- `doj_safe_childhood_2026_012` sentence imposed `supervised release` — real_wrong
  - ing his term of imprisonment, Toler will be required to serve a 10Iyear term of supervised release. There is no parole in the federal system. Toler was also ordered to pay $48,50
- `doj_safe_childhood_2024_420` sentence imposed `mandatory minimum` — real_wrong
  - as a deputy. Bennett is scheduled to be sentenced on June 26, 2024, and faces a mandatory minimum of 15 years and up to 30 years in prison, at least five years and up to a lifet
- `doj_safe_childhood_2024_420` sentence imposed `15 years` — real_wrong
  - is scheduled to be sentenced on June 26, 2024, and faces a mandatory minimum of 15 years and up to 30 years in prison, at least five years and up to a lifetime of supervised release, and
- `doj_safe_childhood_2024_420` sentence imposed `30 years` — real_wrong
  - sentenced on June 26, 2024, and faces a mandatory minimum of 15 years and up to 30 years in prison, at least five years and up to a lifetime of supervised release, and a $250,000 fine. Bennett must a
- `doj_safe_childhood_2024_420` sentence imposed `supervised release` — real_wrong
  - years and up to 30 years in prison, at least five years and up to a lifetime of supervised release, and a $250,000 fine. Bennett must also register as a sex offender. “The defend
- `ncmec_2024_1061` sentence imposed `10 years` — real_wrong
  - of Child Pornography is a Class Four felony which carries a maximum penalty of 10 years in prison and a 20-thousand dollar fine.
- `nj_ag_2023_001` sentence imposed `$15,000` — real_wrong
  - e charges carry a sentence of three of five years in prison and a fine of up to $15,000. Fourth-degree charges carry a sentence of up to 18 months in prison and a fine
- `nj_ag_2023_001` sentence imposed `18 months` — real_wrong
  - on and a fine of up to $15,000. Fourth-degree charges carry a sentence of up to 18 months in prison and a fine of up to $10,000. The charges against the defendants are m
- `nj_ag_2023_001` sentence imposed `$10,000` — real_wrong
  - egree charges carry a sentence of up to 18 months in prison and a fine of up to $10,000. The charges against the defendants are merely accusations and they are presume
- `nj_ag_2026_001` sentence imposed `$15,000` — real_wrong
  - e charges carry a sentence of three to five years in prison and a fine of up to $15,000. Fourth-degree offenses carry a sentence of up to 18 months in state prison and
- `nj_ag_2026_001` sentence imposed `18 months` — real_wrong
  - n and a fine of up to $15,000. Fourth-degree offenses carry a sentence of up to 18 months in state prison and a fine of up to $10,000.
- `nj_ag_2026_001` sentence imposed `$10,000` — real_wrong
  - ffenses carry a sentence of up to 18 months in state prison and a fine of up to $10,000.
- `scag_icac_2023_045` sentence imposed `10 years` — real_wrong
  - on of a minor, second degree (§16-15-405), a felony offense punishable by up to 10 years imprisonment on each count. The case will be prosecuted by the Attorney General
- `scag_icac_2021_030` sentence imposed `10 years` — real_wrong
  - on of a minor, second degree (§16-15-405), a felony offense punishable by up to 10 years imprisonment on each count. Howe was arrested on January 6, 2021. He is charged
- `scag_icac_2022_057` sentence imposed `10 years` — real_wrong
  - ion of a minor, third degree (§16-15-410), a felony offense punishable by up to 10 years imprisonment. This case will be prosecuted by the Attorney General's Office. At
- `scag_icac_2025_116` sentence imposed `10 years` — real_wrong
  - inal solicitation of a minor (§16-15-342), a felony offense punishable by up to 10 years imprisonment on each count; and one count of attempted dissemination of obscene
- `scag_icac_2021_035` sentence imposed `10 years` — real_wrong
  - on of a minor, second degree (§16-15-405), a felony offense punishable by up to 10 years imprisonment. This case will be prosecuted by the Attorney General's Office. At
- `scag_icac_2021_002` sentence imposed `10 years` — real_wrong
  - on of a minor, second degree (§16-15-405), a felony offense punishable by up to 10 years imprisonment on each count. This case will be prosecuted by the Attorney Genera
- `scag_icac_2025_031` sentence imposed `10 years` — real_wrong
  - on of a minor, second degree (§16-15-405), a felony offense punishable by up to 10 years imprisonment on each count. Roper was arrested on October 1, 2025. He is charge
- `svicac_2022_016` sentence imposed `20 years` — real_wrong
  - ild pornography, authorities said. If convicted of the count, Risso faces up to 20 years in prison and a $250,000 fine. On Feb. 15, Federal Bureau of Investigation agen
- `svicac_2022_016` sentence imposed `$250,000` — real_wrong
  - ies said. If convicted of the count, Risso faces up to 20 years in prison and a $250,000 fine. On Feb. 15, Federal Bureau of Investigation agents served a search warran
- `usss_2016_002` sentence imposed `mandatory minimum sentence` — real_wrong
  - oring a number of those images on his mobile telephone. Mahannah faced a higher mandatory minimum sentence because he has a prior conviction for a sex offense – specifically, a 2009 conv
- `wy_dci_2024_004` sentence imposed `264 years` — real_wrong
  - n Center. If convicted, Phillips, arrested last week, faces a sentence of up to 264 years in prison and a fine of up to $240,000. The case began in Montgomery County, Te
- `wy_dci_2024_004` sentence imposed `$240,000` — real_wrong
  - ed last week, faces a sentence of up to 264 years in prison and a fine of up to $240,000. The case began in Montgomery County, Texas, in May when an undercover agent fr

### phase3

- `doj_archives_2007_003` age victims `5` — false_flag
  - ictment, between approximately January 1990 and December 1999, Jorandby knowingly enticed and coerced a female child, who was approximately five years old at the time the crimes began, to engage in sexually explicit conduct involving the lascivious exhibition of the child’s genitals,
- `doj_ceos_2013_138` age victims `15` — false_flag
  - Parkville Woman Sentenced To 15 Years In Prison For Conspiring To Produce Child Pornography September 03, 2013 Publication date
- `doj_safe_childhood_2024_251` age perpetrators `30` — false_flag
  - date: 2024-07-10 Source: AUGUSTA, GA: A Columbia County man has been sentenced to nearly 30 years in federal prison after pleading guilty to producing images of child sexual exploitation.
- `doj_safe_childhood_2025_397` sentence imposed `five years supervised release` — false_flag
  - aylor Bloomgren, 23, was sentenced to five years in federal prison, followed by five years of supervised release, and ordered to pay a $100 special assessment to the Federal Crime Victims Fund
- `doj_safe_childhood_2022_308` age victims `8` — false_flag
  - igation revealed Borjas had over 1900 images and 17 video files depicting child pornography. Borjas also admitted to sexually assaulting an eight-year-old child. On June 22, 2021, Borjas pleaded guilty to one count of receipt of child pornography. Borjas has remained in federal custod
- `doj_safe_childhood_2025_278` sentence imposed `ten-year supervised release` — false_flag
  - . After completing his term of imprisonment, Carter will be required to serve a ten-year term of supervised release. There is no parole in the federal system. United States Attorney Richard D. We
- `doj_safe_childhood_2024_179` age victims `13` — false_flag
  - he investigator viewed the video files and found they were created in January and February of 2019, when the minor victim was approximately thirteen years old. The videos corroborated Chang’s statements regarding the sexual encounters involving him, his spouse, and the minor victim. One

