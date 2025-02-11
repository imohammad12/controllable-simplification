import torch
from utils import *
import os
import math
import numpy as np
# from model.SARI import calculate
from nltk.translate.bleu_score import sentence_bleu, SmoothingFunction, corpus_bleu
from tqdm import tqdm

sf = SmoothingFunction()


def sample(complex_sentences, input_lang, tag_lang, dep_lang, idf, start_time, config,
           tokenizer_deberta, comp_simp_class_model, ccd, model_grammar_checker,
           tokenizer_paraphrasing=None, model_paraphrasing=None):
    count = 0
    all_par_calls = 0
    beam_calls = 0
    start_index = config['start_index']
    stats = {'ls': 0, 'dl': 0, 'las': 0, 'rl': 0, 'par': 0}

    # if config['score_function'] == 'old':
    #     lm_forward.load_state_dict(torch.load(config['lm_name'] + '.pt'))
    # if config['double_LM']:
    #     lm_backward.load_state_dict(torch.load('structured_lm_backward_300_150_0_4.pt'))
    # lm_forward.eval()
    # lm_backward.eval()

    if config['start_index'] != 0:
        sys_sents = read_sys_out_resume(".", config)
    else:
        sys_sents = []

    for i in tqdm(range(start_index, len(complex_sentences)), desc='Simplifying Sentences'):
        if len(complex_sentences[i].split(' ')) <= config['min_length']:

            par_calls, b_calls, out_sent = mcmc(complex_sentences[i], input_lang, tag_lang, dep_lang, idf, stats,
                                                config, tokenizer_deberta, comp_simp_class_model, ccd,
                                                model_grammar_checker, tokenizer_paraphrasing, model_paraphrasing)

            sys_sents.append(out_sent)

            all_par_calls += par_calls
            beam_calls += b_calls

            end = time.time()
            # print(f"Runtime of the program is {end - start_time}")
            # print(f"total paraphrasing calls {all_par_calls}, total beam calls {beam_calls}")

            count += 1

    sari_scores = calculate_sari_easse(ref_folder_path=config["ref_folder_path"], sys_sents=sys_sents,
                                       orig_file_path=config['orig_file_path'])
    simil_simp_gram_scores = similarity_simplicity_grammar_assess(sys_sents=sys_sents,
                                                                  orig_file_path=config['orig_file_path'],
                                                                  tokenizer_deberta=tokenizer_deberta,
                                                                  comp_simp_class_model=comp_simp_class_model,
                                                                  model_grammar_checker=model_grammar_checker)

    runtime = time.time() - start_time
    all_scores = {**sari_scores, **simil_simp_gram_scores, **stats, "runtime": runtime}
    # ccd.params.update(config)
    # config.update(ccd.params)
    print("all scores", all_scores)

    save_and_log(all_scores, sys_sents, config)

    # print(stats)


def mcmc(input_sent, input_lang, tag_lang, dep_lang, idf,
         stats, config, tokenizer_deberta, comp_simp_class_model, ccd,
         model_grammar_checker, tokenizer_paraphrasing, model_paraphrasing):
    # print(stats)
    # input_sent = "highlights 2009 from the 2009 version of 52 seconds setup for passmark 5 32 5 2nd scan time , and 7 mb memory- 7 mb memory ."
    # reference = reference.lower()
    given_complex_sentence = input_sent.lower()
    # final_sent = input_sent
    orig_sent = input_sent
    # print(given_complex_sentence)
    beam = {}
    entities = get_entities(input_sent)
    perplexity = -10000
    perpf = -10000
    synonym_dict = {}
    sent_list = []
    spl = input_sent.lower().split(' ')

    # new_testing
    all_par_calls = 0
    beam_calls = 0

    # creating reverse stem for all words
    stemmer = create_reverse_stem()

    # the for loop below is just in case if the edit operations go for a very long time
    # in almost all the cases this will not be required

    for iter in range(2 * len(spl)):


        # doc = nlp(input_sent)
        # elmo_tensor, \
        # input_sent_tensor, \
        # tag_tensor, \
        # dep_tensor = tokenize_sent_special(input_sent.lower(), input_lang,
        #                                    convert_to_sent([(tok.tag_).upper() for tok in doc]), tag_lang,
        #                                    convert_to_sent([(tok.dep_).upper() for tok in doc]), dep_lang, config)

        prob_old = calculate_score(input_sent, orig_sent, config, tokenizer_deberta, comp_simp_class_model,
                                   model_grammar_checker)

        # for the first time step the beam size is 1, just the original complex sentence
        if iter == 0:
            beam[input_sent] = [prob_old, 'original']
        # print('Getting candidates for iteration: ', iter)
        # print(input_sent)
        new_beam = {}
        # intialize the candidate beam
        for key in beam:

            # new_testing
            beam_calls += 1

            # get candidate sentence through different edit operations
            candidates = get_subphrase_mod(key, sent_list, input_lang, idf, spl, entities, synonym_dict, stemmer,
                                           beam[key], ccd, config, tokenizer_paraphrasing, model_paraphrasing)

            # new_testing
            all_par_calls += candidates[1]
            candidates = candidates[0]
            # print(f"per sentence accumulative all paraphrasing calls is {all_par_calls}, in beam number {beam_calls}")
            # print('candidates are ', candidates)
            '''if len(candidates) == 0:
                break'''

            for i in range(len(candidates)):
                # print(candidate)
                sent = list(candidates[i].keys())[0]
                operation = candidates[i][sent]
                doc = nlp(list(candidates[i].keys())[0])

                # elmo_tensor, candidate_tensor, candidate_tag_tensor, candidate_dep_tensor = tokenize_sent_special(
                #     sent.lower(), input_lang, convert_to_sent([(tok.tag_).upper() for
                #                                                tok in doc]), tag_lang,
                #     convert_to_sent([(tok.dep_).upper() for tok in doc]), dep_lang, config)

                # calculate score for each candidate sentence using the scoring function
                p = calculate_score(sent, orig_sent, config, tokenizer_deberta, comp_simp_class_model,
                                    model_grammar_checker)

                # no repetitive sentence
                sent_list.append(sent)
                # if the candidate sentence is able to increase the score by a threshold value, add it to the beam
                if p > prob_old * config['threshold'][operation]:
                    new_beam[sent] = [p, operation, orig_sent]
                    # print('This sentence added to beam:', sent)
                # else:
                #     # if the threshold is not crossed, add it to a list so that the sentence is not considered in the future
                #     sent_list.append(sent)
        if new_beam == {}:
            # if there are no candidate sentences, exit
            break
        # print(new_beam)
        new_beam_sorted_list = sorted(new_beam.items(), key=lambda x: x[1])[-config['beam_size']:]
        # sort the created beam on the basis of scores from the scoring function
        new_beam = {}
        # top k top scoring sentences selected. In our experiments the beam size is 1
        # copying the new_beam_sorted_list into new_beam
        for key in new_beam_sorted_list:
            new_beam[key[0]] = key[1]
        # new_beam = new_beam_sorted_list.copy()
        # we'll get top beam_size (or <= beam size) candidates

        # get the top scoring sentence. This will act as the source sentence for the next iteartion
        max_candidate = max(new_beam.items(), key=lambda x: x[1])
        maxvalue_sent = max_candidate[0]

        for accepted_sent, details_sent in new_beam.items():
            # record the edit operation by which the candidate sentence was created
            stats[details_sent[1]] += 1

            # print(f"accepted sentence: {accepted_sent}\n new prob: {details_sent[0]}, old prob: {prob_old}"
            #       f"operation: {details_sent[1]}")
            # if the operation used for this candidate sentence is paraphrasing
            # we save the root of negative constraints used in this step and add them to
            # negative constraints in the next steps to prevent from looping between synonym words
            if details_sent[1] == 'par':
                unchanged_sent = details_sent[2]
                neg_consts = ccd.extract_complex_words(unchanged_sent, entities)[0]
                details_sent.append(neg_consts)

        perpf = new_beam[maxvalue_sent][0]
        input_sent = maxvalue_sent
        # for the next iteration
        beam = new_beam.copy()

    input_sent = input_sent.lower()
    # print(given_complex_sentence)
    # print(reference)
    # print("Input complex sentence")
    # print(given_complex_sentence)
    # print("Reference sentence")
    # print(reference)
    # print("Simplified sentence")
    # print(input_sent)


    # if (perpf == -10000):
        # print('sentence remain unchanged therefore calculating perp score for last generated sentence')
        # doc = nlp(input_sent)
        # elmo_tensor, best_input_tensor, best_tag_tensor, best_dep_tensor = tokenize_sent_special(input_sent.lower(),
        #                                                                                          input_lang,
        #                                                                                          convert_to_sent(
        #                                                                                              [(tok.tag_).upper()
        #                                                                                               for
        #                                                                                               tok in doc]),
        #                                                                                          tag_lang,
        #                                                                                          convert_to_sent(
        #                                                                                              [(tok.dep_).upper()
        #                                                                                               for tok in doc]),
        #                                                                                          dep_lang, config)
        # perpf = calculate_score(input_sent, orig_sent, config, tokenizer_deberta, comp_simp_class_model,
        #                         model_grammar_checker)

        # if config['double_LM']:
        #     elmo_tensor_b, best_input_tensor_b, best_tag_tensor_b, best_dep_tensor_b = tokenize_sent_special(
        #         reverse_sent(input_sent.lower()), input_lang, reverse_sent(convert_to_sent([(tok.tag_).upper() for
        #                                                                                     tok in doc])), tag_lang,
        #         reverse_sent(convert_to_sent([(tok.dep_).upper() for tok in doc])), dep_lang, config)
        #     perpf += calculate_score(lm_backward, elmo_tensor_b, best_input_tensor_b, best_tag_tensor_b,
        #                              best_dep_tensor_b, input_lang, reverse_sent(input_sent), reverse_sent(orig_sent),
        #                              embedding_weights, idf, unigram_prob, False, config, tokenizer_deberta,
        #                              comp_simp_class_model, model_grammar_checker)

    with open(config['resume_file'], "a") as file:
        file.write(given_complex_sentence + "\n")

    return all_par_calls, beam_calls, input_sent
