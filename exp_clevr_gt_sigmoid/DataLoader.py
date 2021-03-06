import numpy as np
import json
import pickle
import torch
import math
from IPython import embed


def invert_dict(d):
    return {v: k for k, v in d.items()}


def load_vocab(path):
    path = str(path)
        
    with open(path, 'r') as f:
        vocab = json.load(f)
        vocab['question_idx_to_token'] = invert_dict(vocab['question_token_to_idx'])
        vocab['program_idx_to_token'] = invert_dict(vocab['program_token_to_idx'])
        vocab['answer_idx_to_token'] = invert_dict(vocab['answer_token_to_idx'])
    return vocab


class ClevrDataset():

    def __init__(self, questions, image_indices, programs, program_inputs, answers,
                       edge_matrixes, vertex_vectors):
        assert len(edge_matrixes) == len(vertex_vectors)

        # convert data to tensor
        self.all_questions = torch.LongTensor(np.asarray(questions))
        self.all_image_idxs = torch.LongTensor(np.asarray(image_indices))
        self.all_programs = torch.LongTensor(np.asarray(programs))
        self.all_program_inputs = torch.LongTensor(np.asarray(program_inputs))
        self.all_answers = torch.LongTensor(np.asarray(answers)) if answers is not None else None

        self.edge_matrixes = { i: torch.LongTensor(np.asarray(m)) for i, m in edge_matrixes.items() }
        self.vertex_vectors = { i: torch.LongTensor(np.asarray(v)) for i, v in vertex_vectors.items() }

    def __getitem__(self, index):
        question = self.all_questions[index]
        image_idx = self.all_image_idxs[index].item()
        program_seq = self.all_programs[index]
        program_input = self.all_program_inputs[index]
        answer = self.all_answers[index] if self.all_answers is not None else None
        assert program_seq.size(0) == program_input.size(0), "program and program_input must have the same length"
        # fetch scene graph via image_idx
        edge_matrix = self.edge_matrixes[image_idx]
        vertex_vector = self.vertex_vectors[image_idx]

        return (question, program_seq, program_input, answer, edge_matrix, vertex_vector)

    def __len__(self):
        return len(self.all_questions)


def clevr_collate(batch):
    transposed = list(zip(*batch))
    question_batch = torch.stack(transposed[0])
    program_seq_batch = transposed[1]
    if transposed[1][0] is not None:
        program_seq_batch = torch.stack(transposed[1])
    # input for program
    program_input_batch = transposed[2]
    if transposed[2][0] is not None:
        program_input_batch = torch.stack(transposed[2])
    answer_batch = torch.stack(transposed[3]) if transposed[3][0] is not None else None

    # matrixes representing the scene graph cannot be aligned because graphs have different number of vertex
    # so they are conveyed as list of tensor
    edge_matrix_batch, vertex_vector_batch = transposed[4], transposed[5]

    return [answer_batch, question_batch, program_seq_batch, program_input_batch,\
            edge_matrix_batch, vertex_vector_batch]


class ClevrDataLoader():

    def __init__(self, **kwargs):
        if 'question_pt' not in kwargs:
            raise ValueError('Must give question_pt')
        if 'scene_pt' not in kwargs:
            raise ValueError('Must give scene_pt')
        if 'vocab_json' not in kwargs:
            raise ValueError('Must give vocab_json')

        scene_pt_path = str(kwargs.pop('scene_pt'))
        print('loading scenes from %s' % (scene_pt_path))
        with open(scene_pt_path, 'rb') as f:
            edge_matrixes = pickle.load(f)
            vertex_vectors = pickle.load(f)
            scene_descs = pickle.load(f)
        vocab_json_path = str(kwargs.pop('vocab_json'))
        print('loading vocab from %s' % (vocab_json_path))
        vocab = load_vocab(vocab_json_path)

        question_pt_path = str(kwargs.pop('question_pt'))
        print('loading questions from %s' % (question_pt_path))
        with open(question_pt_path, 'rb') as f:
            obj = pickle.load(f)
            questions = obj['questions']
            image_indices = obj['image_idxs']
            programs = obj['programs']
            program_inputs = obj['program_inputs']
            answers = obj['answers']

        if 'annotation_json' in kwargs:
            annotations = json.load(open(kwargs.pop('annotation_json')))['scenes']
            self.orig_annotations = { int(s['image_index']):s for s in annotations }

        self.ratio = None
        if 'ratio' in kwargs:
            self.ratio = kwargs.pop('ratio')
            total = int(len(questions) * self.ratio)
            print('training ratio = %.3f, containing %d questions' % (self.ratio, total))
            questions = questions[:total]
            image_indices = image_indices[:total]
            programs = programs[:total]
            program_inputs = program_inputs[:total]
            answers = answers[:total]
        
        self.dataset = ClevrDataset(questions, image_indices, programs, program_inputs, answers,\
                                    edge_matrixes, vertex_vectors)
        self.scene_descs = scene_descs
        self.vocab = vocab
        self.batch_size = kwargs.pop('batch_size')
        self.shuffle = kwargs.pop('shuffle')


    def generator(self):
        random_idxs = np.arange(len(self.dataset))
        if self.shuffle:
            np.random.shuffle(random_idxs)
        for batch_iter in range(0, len(self.dataset), self.batch_size):
            data = []
            self.idx_cache = []
            self.desc_cache = []
            for i in range(batch_iter, min(batch_iter+self.batch_size, len(self.dataset))):
                data.append(self.dataset[random_idxs[i]])
                image_idx = self.dataset.all_image_idxs[random_idxs[i]].item()
                self.idx_cache.append(image_idx)
                self.desc_cache.append(self.scene_descs[image_idx])

            data = clevr_collate(data)
            yield data

    def __len__(self):
        return math.ceil(len(self.dataset) / self.batch_size)

