# Call-a-parent judge (2026-10-24)

model pet-chat-9b: requests found 25/25 (wrong target 0), look-alikes asked about 0/25

judge calls 26, median 2.26 s, max 2.68 s

| sentence | expected | got | path |
|---|---|---|---|
| 我想找爸爸 | dad | dad | fixed |
| 爸爸在哪儿 | dad | dad | judge |
| 爸爸在哪里呀? | dad | dad | judge |
| 我要妈妈 | mom | mom | judge |
| 让妈妈来一下 | mom | mom | fixed |
| 我想爸爸了 | dad | dad | judge |
| 妈妈快来! | mom | mom | judge |
| 妈妈你在哪 | mom | mom | judge |
| 我要爸爸妈妈 | both | both | judge |
| 你们快来看 | both | both | judge |
| 爸爸妈妈快过来 | both | both | judge |
| 我想让妈妈陪我 | mom | mom | judge |
| tell mommy I'm hungry | mom | mom | fixed |
| where's daddy | dad | dad | judge |
| Where is my mom? | mom | mom | judge |
| I want my mom and dad | both | both | judge |
| I need daddy | dad | dad | judge |
| Can mommy come here? | mom | mom | judge |
| I miss my dad | dad | dad | judge |
| get my parents please | both | both | fixed |
| I want my daddy | dad | dad | judge |
| where's mommy | mom | mom | judge |
| 我想 mommy 了 | mom | mom | judge |
| daddy 在哪里? | dad | dad | judge |
| Mommy, come here! | mom | mom | judge |
| 我爸爸是医生 | none | none | prefilter |
| 妈妈说我可以看电视 | none | none | prefilter |
| 爸爸的生日是几号? | none | none | prefilter |
| 讲一个熊爸爸和熊妈妈的故事 | none | none | prefilter |
| 小蝌蚪找妈妈是什么故事? | none | none | judge |
| 为什么爸爸有胡子? | none | none | prefilter |
| 我妈妈做的饭很好吃 | none | none | prefilter |
| 袋鼠妈妈怎么带宝宝? | none | none | prefilter |
| 不要告诉妈妈 | none | none | judge |
| 我和爸爸昨天去了动物园 | none | none | prefilter |
| 妈妈的妈妈叫什么? | none | none | judge |
| 爸爸妈妈是怎么认识的? | none | none | prefilter |
| My dad is tall | none | none | prefilter |
| Why do daddies have beards? | none | none | prefilter |
| My mom says I can have a cookie | none | none | prefilter |
| Tell me a story about a baby bear and his mommy | none | none | judge |
| Do penguin dads keep the eggs warm? | none | none | prefilter |
| Don't tell mom | none | none | judge |
| What's a mother hen? | none | none | prefilter |
| Mom and dad went shopping | none | none | prefilter |
| my dad is a doctor | none | none | prefilter |
| mom said I can watch TV | none | none | prefilter |
| what's daddy's birthday? | none | none | prefilter |
| 我的 daddy 会修车 | none | none | prefilter |
| Peppa's daddy pig is funny | none | none | prefilter |
