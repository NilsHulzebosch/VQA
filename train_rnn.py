import random
import torch
import torch.autograd as autograd
from torch.autograd import Variable
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import numpy as np
from data_reader import read_textual_data, read_image_data
from showme import show_image

# define hyperparameters
NUM_EPOCHS = 3
LEARNING_RATE = 0.01
RNDM_SEED = 42
N_HIDDEN = 1000
torch.manual_seed(RNDM_SEED) # set random seed for continuity

# map img_id to list of visual features corresponding to that image
def img_id_to_features(img_id):
    h5_id = visual_feat_mapping[str(img_id)]
    return img_features[h5_id]

# read in textual (question-answer) data
q_train, q_valid, q_test, a_train, a_valid, a_test = read_textual_data()

# read in visual feature data
img_ids, img_features, visual_feat_mapping, imgid2info = read_image_data()

TRAIN_LEN = int(0.15 * len(q_train))
VALID_LEN = int(0.15 * len(q_valid))
TEST_LEN =  int(0.15 * len(q_test))

def sentence_length_index_count():
    sentence_length_index = [0] * 22
    target_length_index = [0] * 3
    for (sentence, target) in train_data+valid_data+test_data:
        sentence_length_index[len(sentence)] += 1
        target_length_index[len([target])] += 1
    print("Sentences ", sentence_length_index)
    print("Targets   ", target_length_index)

def train_valid_test_data():
# determine train data
    train_data = []
    train_visual_features = []
    for i in range(TRAIN_LEN): # number of instances of train data (10.000 with 3 epochs took 2 hours on my laptop)
        sentence = q_train[i][0].split()
        train_data.append((sentence, a_train[i]))
        train_visual_features.append(img_id_to_features(q_train[i][1]))

    # determine validation data
    valid_data = []
    valid_visual_features = []
    for i in range(VALID_LEN): # number of instances of test data
        sentence = q_valid[i][0].split()
        valid_data.append((sentence, a_valid[i]))
        valid_visual_features.append(img_id_to_features(q_valid[i][1]))

    # determine test data
    test_data = []
    test_visual_features = []
    for i in range(TEST_LEN): # number of instances of test data
        sentence = q_test[i][0].split()
        test_data.append((sentence, a_test[i]))
        test_visual_features.append(img_id_to_features(q_test[i][1]))

    return train_data, train_visual_features, valid_data, valid_visual_features, test_data, test_visual_features

def shuffle_data(text_features, visual_features):
    combined = [(text, visual) for text, visual in zip(text_features, visual_features)]
    random.shuffle(combined)
    return [text for (text, _) in combined], [visual for (_, visual) in combined]
    
# create source_vocabulary and target_vocabulary
# source_vocabulary maps each word in the vocab to a unique integer, 
# which will be its index into the Bag of Words vector
def vocabulary():
    source_vocabulary = {}
    target_vocabulary = {}
    target_vocabulary_lookup = []
    for sent, label in train_data + valid_data + test_data:
        for word in sent:
            if word not in source_vocabulary:
                source_vocabulary[word] = len(source_vocabulary)
        if label not in target_vocabulary:
            target_vocabulary[label] = len(target_vocabulary)
            target_vocabulary_lookup.append(label)

    source_vocabulary['<pad>'] = len(source_vocabulary)
    return source_vocabulary, target_vocabulary, target_vocabulary_lookup

train_data, train_visual_features, valid_data, valid_visual_features, test_data, test_visual_features = train_valid_test_data()
source_vocabulary, target_vocabulary, target_vocabulary_lookup = vocabulary()

# calculate size of both vocabularies
VOCAB_SIZE = len(source_vocabulary) # amount of unique words in questions
NUM_LABELS = len(target_vocabulary) # amount of unique words in answers
IMG_FEAT_SIZE = len(train_visual_features[0])
print('Source vocabulary size:', VOCAB_SIZE, '  ', len(source_vocabulary))
print('Target vocabulary size:', NUM_LABELS, '    ', len(target_vocabulary))

def get_training_pair(sentence, label, source_vocabulary, target_vocabulary, visual_features):
    return Variable(make_input_tensor(sentence, source_vocabulary, visual_features)), \
    Variable(make_target_tensor(label, target_vocabulary))

def make_input_tensor(sentence, source_vocabulary, visual_features): 
    vec = torch.zeros(len(sentence), 1, len(source_vocabulary) + len(visual_features))
    for i, word in enumerate(sentence):
        vec[i][0][source_vocabulary[word]] += 1
        for j in range(len(visual_features)):
            vec[i][0][j+len(source_vocabulary)] += visual_features[j]
    return vec

def make_target_tensor(label, target_vocabulary):
    return torch.LongTensor([target_vocabulary[label]])


###########################################################
###################### RNN MODEL ##########################
###########################################################

# define a class for the RNN model
class RNN(nn.Module):
    def __init__(self, input_size, hidden_size, output_size):
        super(RNN, self).__init__()
        
        self.input_size = input_size
        self.hidden_size = hidden_size
        self.output_size = output_size
        
        self.i2h = nn.Linear(input_size + hidden_size, hidden_size)
        self.i2o = nn.Linear(input_size + hidden_size, output_size)
        self.softmax = nn.LogSoftmax(dim=-1)
        
    def forward(self, input, hidden):
        combined = torch.cat((input, hidden), 1)
        hidden = self.i2h(combined)
        output = self.i2o(combined)
        output = self.softmax(output)
        return output, hidden

    def init_hidden(self):
        return Variable(torch.zeros(1, self.hidden_size))

# initialize a RNN model
rnn = RNN(VOCAB_SIZE + IMG_FEAT_SIZE, N_HIDDEN, NUM_LABELS)

# intialize loss function (= Negative Log Likelihood Loss)
loss_function = nn.NLLLoss()

# intialize optimizer (= Stochastic Gradient Descent)
optimizer = optim.SGD(rnn.parameters(), lr=LEARNING_RATE)

# 
def train(answer_tensor, question_tensor):
    rnn.zero_grad()
    hidden = rnn.init_hidden()
    
    for i in range(question_tensor.size()[0]):
        output, hidden = rnn(question_tensor[i], hidden)

    loss = loss_function(output, answer_tensor)
    loss.backward()

    optimizer.step()

    return output, loss.data[0]

# train the model on train_data for NUM_EPOCHS epochs
def train_rnn():
    
    # keep track of losses for plotting
    current_loss = 0
    all_losses = []
    
    for iter in range(1, NUM_EPOCHS+1):
        print("EPOCH:", iter, " / ", NUM_EPOCHS)
        counter = 1
        for (question, answer), visual_features in zip(*shuffle_data(train_data, train_visual_features)):
            question_tensor, target_tensor = get_training_pair(question, answer, \
                source_vocabulary, target_vocabulary, visual_features)

            output, loss = train(target_tensor, question_tensor)
            current_loss += loss
            
            if counter % 100 == 0:
                print(counter, "/", len(train_data), ' | ', current_loss / counter)
            counter += 1

        # add current loss avg to list of losses
        all_losses.append(current_loss)
        value, index = torch.max(output, 1)
        print("Average loss", current_loss)
        print("validation accuracy", calc_accuracy(rnn, valid_data, valid_visual_features))
        current_loss = 0
            
    return rnn, all_losses



def calc_accuracy(model, data, visual_features):
    counter = 0
    for (question, correct_answer), vis_features in zip(data, visual_features):
        input_tensor = Variable(make_input_tensor(question, source_vocabulary, vis_features))
        hidden = model.init_hidden()

        for i in range(input_tensor.size()[0]):
            output, hidden = model(input_tensor[i], hidden)
       
        value, index = torch.max(output, 1)
        index = index.data[0]
        predicted_answer = target_vocabulary_lookup[index]

        if predicted_answer == correct_answer:
            counter += 1
   
    accuracy = (float(counter) / len(data)) * 100
    return accuracy



if __name__ == "__main__":
    trained_rnn, all_losses = train_rnn()
    
    print("Trained RNN model:\n", trained_rnn)
    print("Average loss of each epoch:\n", all_losses)
    
    accuracy = calc_accuracy(rnn, test_data, test_visual_features)
    print("The accuracy of RNN on test data is: ", accuracy, "%")
